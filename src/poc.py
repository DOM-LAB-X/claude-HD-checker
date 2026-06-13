import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db
from src.config import load_config
from src.price_checker import PARSER_VERSION, check_product

PRODUCT_URL = (
    "https://www.homedepot.com/p/DEWALT-20V-MAX-XR-Lithium-Ion-Cordless-2-1-2-in-"
    "15-Gauge-Finish-Nailer-Kit-with-2-0Ah-Battery-Charger-and-Contractor-Bag-"
    "DCN650D1/301424967"
)
ITEM_ID = "301424967"


async def main():
    config = load_config(str(Path(__file__).resolve().parent.parent / "config.yaml"))
    conn = db.connect(str(Path(__file__).resolve().parent.parent / config.db_path))

    product_id = db.upsert_product(
        conn,
        internet_number=ITEM_ID,
        store_sku=None,
        model_number=None,
        name=None,
        brand=None,
        url=PRODUCT_URL,
    )

    stores = config.stores[:]
    random.shuffle(stores)
    print(f"Checking stores in order: {stores}\n")

    results = []
    for i, store_id in enumerate(stores):
        print(f"--- Store {store_id} ---")
        result = await check_product(PRODUCT_URL, ITEM_ID, store_id, config.zip_code)
        print(f"  result_state: {result.result_state}")
        print(f"  store_verified: {result.store_verified}")
        if result.online_price_cents is not None:
            print(f"  online_price: ${result.online_price_cents / 100:.2f}")
        if result.clearance_price_cents is not None:
            print(f"  clearance_price: ${result.clearance_price_cents / 100:.2f} ({result.savings_pct}% off)")
        if result.error_detail:
            print(f"  error_detail: {result.error_detail}")

        if result.product_label:
            db.update_product_metadata(
                conn,
                product_id=product_id,
                store_sku=result.store_sku,
                model_number=result.model_number,
                name=result.product_label,
                brand=result.brand_name,
            )

        db.insert_observation(
            conn,
            product_id=product_id,
            store_id=store_id,
            online_price_cents=result.online_price_cents,
            clearance_price_cents=result.clearance_price_cents,
            savings_pct=result.savings_pct,
            result_state=result.result_state,
            store_verified=result.store_verified,
            parser_version=PARSER_VERSION,
            error_detail=result.error_detail,
        )
        results.append((store_id, result))

        if i < len(stores) - 1:
            delay = random.uniform(*config.between_stores_sec)
            print(f"  (waiting {delay:.1f}s before next store)\n")
            await asyncio.sleep(delay)

    print("\n=== Summary ===")
    for store_id, result in results:
        online = f"${result.online_price_cents/100:.2f}" if result.online_price_cents else "-"
        clearance = f"${result.clearance_price_cents/100:.2f}" if result.clearance_price_cents else "-"
        print(f"Store {store_id}: {result.result_state:<22} online={online:<10} clearance={clearance:<10} verified={result.store_verified}")

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
