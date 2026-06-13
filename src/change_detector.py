"""Phase 3 change detection (observation-only).

Compares the most recent `clearance_price_found` observation against the
previous one for each product+store pair, and flags notable events. Events
are recorded in the `change_events` table. Sending notifications for these
events is a separate, later step (controlled by `alerts.observation_only`).
"""
from typing import Dict, List

from src import db


def detect_changes(conn, config, product_ids: Dict[str, int], stores: List[str]) -> List[dict]:
    events = []
    alerts_cfg = config.alerts

    for internet_number, product_id in product_ids.items():
        latest_clearance_by_store = {}

        for store_id in stores:
            rows = db.last_clearance_observations(conn, product_id, store_id, limit=2)
            if not rows:
                continue

            latest = rows[0]
            checked_at, online_cents, clearance_cents, savings_pct = latest
            latest_clearance_by_store[store_id] = clearance_cents

            if len(rows) == 1:
                event = dict(
                    product_id=product_id, store_id=store_id, event_type="first_clearance",
                    old_clearance_price_cents=None, new_clearance_price_cents=clearance_cents,
                    online_price_cents=online_cents, savings_pct=savings_pct,
                    details=f"First clearance price observed at store {store_id}",
                )
                events.append(event)
            else:
                _, _, prev_clearance_cents, _ = rows[1]
                if clearance_cents < prev_clearance_cents:
                    event = dict(
                        product_id=product_id, store_id=store_id, event_type="price_drop",
                        old_clearance_price_cents=prev_clearance_cents, new_clearance_price_cents=clearance_cents,
                        online_price_cents=online_cents, savings_pct=savings_pct,
                        details=f"Clearance price dropped from ${prev_clearance_cents/100:.2f} to ${clearance_cents/100:.2f}",
                    )
                    events.append(event)

            # Threshold check
            if (
                (alerts_cfg.get("min_savings_pct") and savings_pct is not None and savings_pct >= alerts_cfg["min_savings_pct"])
                or (alerts_cfg.get("min_savings_amount") and online_cents and clearance_cents
                    and (online_cents - clearance_cents) >= alerts_cfg["min_savings_amount"])
            ):
                events.append(dict(
                    product_id=product_id, store_id=store_id, event_type="meets_alert_threshold",
                    old_clearance_price_cents=None, new_clearance_price_cents=clearance_cents,
                    online_price_cents=online_cents, savings_pct=savings_pct,
                    details=f"Clearance ${clearance_cents/100:.2f} meets alert thresholds "
                            f"(min_savings_pct={alerts_cfg.get('min_savings_pct')}, "
                            f"min_savings_amount={alerts_cfg.get('min_savings_amount')})",
                ))

            # Product returned after being unavailable
            prev_state = db.last_observation_before(conn, product_id, store_id, checked_at)
            if prev_state and prev_state[0] == "product_unavailable":
                events.append(dict(
                    product_id=product_id, store_id=store_id, event_type="product_returned",
                    old_clearance_price_cents=None, new_clearance_price_cents=clearance_cents,
                    online_price_cents=online_cents, savings_pct=savings_pct,
                    details=f"Product was unavailable at store {store_id}, now has a clearance price",
                ))

        # Inter-store price difference
        if len(latest_clearance_by_store) >= 2:
            min_store = min(latest_clearance_by_store, key=lambda s: latest_clearance_by_store[s])
            max_store = max(latest_clearance_by_store, key=lambda s: latest_clearance_by_store[s])
            min_price = latest_clearance_by_store[min_store]
            max_price = latest_clearance_by_store[max_store]
            if min_price > 0:
                diff_pct = (max_price - min_price) / min_price * 100
                if diff_pct >= alerts_cfg.get("inter_store_diff_pct", 15):
                    events.append(dict(
                        product_id=product_id, store_id=None, event_type="inter_store_diff",
                        old_clearance_price_cents=max_price, new_clearance_price_cents=min_price,
                        online_price_cents=None, savings_pct=diff_pct,
                        details=f"Store {min_store} is ${min_price/100:.2f} vs store {max_store} "
                                f"${max_price/100:.2f} ({diff_pct:.0f}% cheaper)",
                    ))

    for event in events:
        db.insert_change_event(conn, **event)

    return events
