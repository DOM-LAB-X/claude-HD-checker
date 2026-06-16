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


async def run_cycle(config=None, item_numbers: list | None = None):
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

    run_id = db.start_run(conn)
    products_attempted = 0
    products_succeeded = 0
    stores_with_errors = []
    rate_limited_overall = False

    for store_idx, store_id in enumerate(stores):
        print(f"\n=== Store {store_id} ===")
        store_had_error = False
        store_rate_limited = False

        async with store_session(store_id, config.zip_code) as context:
            for prod_idx, entry in enumerate(watchlist):
                if store_rate_limited:
                    # skip remaining products at this store once rate-limited
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

                if prod_idx < len(watchlist) - 1 and not store_rate_limited:
                    delay = random.uniform(*config.between_products_sec)
                    await asyncio.sleep(delay)

        if store_had_error:
            stores_with_errors.append(store_id)

        if store_idx < len(stores) - 1:
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

        if not observation_only:
            send_alerts(conn, config, events)
    else:
        print("\nNo change events detected.")

    conn.close()


ALERTABLE_EVENT_TYPES = {"first_clearance", "price_drop", "product_returned", "inter_store_diff"}


def send_alerts(conn, config, events):
    webhook_url = config.alerts.get("discord_webhook_url", "")
    if not webhook_url:
        return
    for e in events:
        if e["event_type"] not in ALERTABLE_EVENT_TYPES:
            continue
        product = db.get_product(conn, e["product_id"])
        name = product[1] or product[0] if product else str(e["product_id"])
        url = product[2] if product else ""
        store_label = f"Store {e['store_id']}" if e["store_id"] else "All stores"
        content = f"**[{e['event_type']}]** {name}\n{store_label}: {e['details']}\n{url}"
        send_discord_message(webhook_url, content)


if __name__ == "__main__":
    asyncio.run(run_cycle())
