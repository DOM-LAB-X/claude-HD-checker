import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db
from src.change_detector import detect_changes
from src.config import PROJECT_ROOT, _ensure_user_file, load_config
from src.notifier import send_discord_message
from src.price_checker import PARSER_VERSION, check_product_in_context, store_session
from src.watchlist import load_watchlist


async def run_cycle(config=None, item_numbers: list | None = None, stop_event=None):
    config = config or load_config()
    conn = db.connect(str(PROJECT_ROOT / config.db_path))
    watchlist = load_watchlist(str(_ensure_user_file(config.watchlist_path)))
    if item_numbers:
        watchlist = [e for e in watchlist if e.internet_number in item_numbers]

    product_ids = {}
    for entry in watchlist:
        product_ids[entry.internet_number] = db.upsert_product(
            conn,
            internet_number=entry.internet_number,
            store_sku=None,
            model_number=None,
            name=None,
            brand=None,
            url=entry.url,
        )

    stores = config.stores[:]
    random.shuffle(stores)
    print(f"Run order: stores={stores}, products={len(watchlist)}")

    def _cancelled():
        return stop_event is not None and stop_event.is_set()

    run_id = db.start_run(conn)
    products_attempted = 0
    products_succeeded = 0
    stores_with_errors = []
    rate_limited_overall = False

    for store_idx, store_id in enumerate(stores):
        if _cancelled():
            print("Run cancelled.")
            break
        print(f"\n=== Store {store_id} ===")
        store_had_error = False
        store_rate_limited = False

        async with store_session(store_id, config.zip_code) as context:
            for prod_idx, entry in enumerate(watchlist):
                if _cancelled() or store_rate_limited:
                    break

                result = None
                attempts = 1 + config.max_retries_per_product
                for attempt in range(attempts):
                    products_attempted += 1
                    result = await check_product_in_context(context, entry.url, store_id)
                    products_succeeded += int(result.result_state in (
                        "clearance_price_found", "not_currently_clearance"
                    ))
                    if result.result_state != "temporary_error" or attempt == attempts - 1:
                        break
                    print(f"  retrying {entry.internet_number} after temporary_error")

                print(f"  {entry.internet_number}: {result.result_state}"
                      + (f" online=${result.online_price_cents/100:.2f}" if result.online_price_cents else "")
                      + (f" clearance=${result.clearance_price_cents/100:.2f} ({result.savings_pct}% off)" if result.clearance_price_cents else ""))

                if result.product_label:
                    db.update_product_metadata(
                        conn,
                        product_id=product_ids[entry.internet_number],
                        store_sku=result.store_sku,
                        model_number=result.model_number,
                        name=result.product_label,
                        brand=result.brand_name,
                    )

                db.insert_observation(
                    conn,
                    product_id=product_ids[entry.internet_number],
                    store_id=store_id,
                    online_price_cents=result.online_price_cents,
                    clearance_price_cents=result.clearance_price_cents,
                    savings_pct=result.savings_pct,
                    result_state=result.result_state,
                    store_verified=result.store_verified,
                    parser_version=PARSER_VERSION,
                    error_detail=result.error_detail,
                )

                if result.result_state == "rate_limited_or_blocked":
                    store_rate_limited = True
                    rate_limited_overall = True
                    store_had_error = True
                elif result.result_state in (
                    "temporary_error", "store_mismatch", "page_layout_changed",
                ):
                    store_had_error = True

                if prod_idx < len(watchlist) - 1 and not store_rate_limited and not _cancelled():
                    delay = random.uniform(*config.between_products_sec)
                    await asyncio.sleep(delay)

        if store_had_error:
            stores_with_errors.append(store_id)

        if store_idx < len(stores) - 1 and not _cancelled():
            delay = random.uniform(*config.between_stores_sec)
            print(f"  (waiting {delay:.1f}s before next store)")
            await asyncio.sleep(delay)

    db.finish_run(
        conn,
        run_id,
        products_attempted=products_attempted,
        products_succeeded=products_succeeded,
        stores_with_errors=stores_with_errors,
        rate_limited=rate_limited_overall,
    )

    print(f"\n=== Run {run_id} complete: {products_succeeded}/{products_attempted} succeeded, "
          f"stores_with_errors={stores_with_errors}, rate_limited={rate_limited_overall} ===")

    events = detect_changes(conn, config, product_ids, config.stores)
    observation_only = config.alerts.get("observation_only", True)

    if events:
        print(f"\n=== Change events ({'observation-only, not sent' if observation_only else 'alerting'}) ===")
        for e in events:
            store_label = f"store {e['store_id']}" if e["store_id"] else "all stores"
            print(f"  [{e['event_type']}] product {e['product_id']} ({store_label}): {e['details']}")
    else:
        print("\nNo change events detected.")

    if not observation_only:
        send_run_summary(conn, config, product_ids, events)

    conn.close()


def _fmt(cents) -> str:
    return f"${cents / 100:.2f}" if cents is not None else "—"


def send_run_summary(conn, config, product_ids: dict, events: list) -> None:
    """Send one Discord message per check with all current clearance prices and any change tags."""
    webhook_url = config.alerts.get("discord_webhook_url", "")
    if not webhook_url:
        return

    # Index events by (product_id, store_id) so we can annotate each store line.
    event_map: dict[tuple, str] = {}
    for e in events:
        key = (e["product_id"], e.get("store_id"))
        t = e["event_type"]
        if t == "first_clearance":
            event_map[key] = "🆕"
        elif t == "price_drop":
            old = e.get("old_clearance_price_cents")
            event_map[key] = f"📉 was {_fmt(old)}"
        elif t == "product_returned":
            event_map[key] = "🔄 back"
        elif t == "inter_store_diff":
            event_map[(e["product_id"], None)] = "🏪 price diff between stores"

    product_sections = []
    for internet_number, product_id in product_ids.items():
        product = db.get_product(conn, product_id)
        if not product:
            continue
        name = (product[1] or internet_number)[:80]
        url = product[2] or ""

        store_lines = []
        for store_id in config.stores:
            rows = db.last_clearance_observations(conn, product_id, store_id, limit=1)
            if not rows:
                continue
            _, online_cents, clearance_cents, savings_pct = rows[0]
            if not clearance_cents:
                continue
            savings_str = f" 🔥 **{savings_pct:.0f}% off**" if savings_pct else ""
            online_str = f"~~{_fmt(online_cents)}~~ → " if online_cents else ""
            tag = event_map.get((product_id, store_id), "")
            tag_str = f"  — {tag}" if tag else ""
            store_lines.append(
                f"  📍 Store {store_id}:  {online_str}**{_fmt(clearance_cents)}**{savings_str}{tag_str}"
            )

        if store_lines:
            product_sections.append(
                f"**{name}**\n" + "\n".join(store_lines) + f"\n  🔗 {url}"
            )

    if not product_sections:
        return

    content = "🔍 **HD Clearance Check Results**\n\n" + "\n\n".join(product_sections)
    send_discord_message(webhook_url, content)


if __name__ == "__main__":
    asyncio.run(run_cycle())
