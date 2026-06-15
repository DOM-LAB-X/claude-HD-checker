#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python3 -c "
import asyncio
from src.config import load_config
from src.run_cycle import run_cycle
asyncio.run(run_cycle(load_config()))
"
