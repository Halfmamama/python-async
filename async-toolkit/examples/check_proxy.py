import asyncio
import sys
import os

# Append parent directory to sys.path to run the example directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy_health import confirm_proxy_dead
from logger import setup_logger

async def main():
    # Setup standard logger
    logger, log_file = setup_logger(log_name="check_proxy_example.log")
    logger.info("Starting proxy health checker example...")

    # Let's test a broken proxy that is guaranteed to fail
    broken_proxy = {
        "server": "127.0.0.1:9999",
        "username": "dummy_user",
        "password": "dummy_password_12345"
    }

    # Re-setup logger with masking enabled for password
    # In a real app, passwords are masked to avoid leak in logs
    setup_logger(
        log_name="check_proxy_example.log",
        secrets_to_mask=["dummy_password_12345"]
    )

    logger.info("Scanning a known broken proxy (expected to confirm dead)...")
    
    # Run async checker
    is_dead = await confirm_proxy_dead(broken_proxy, retries=2)
    
    logger.info(f"Scan finished. Result: Is proxy dead? -> {is_dead}")
    print(f"\n--- Check completed. Is proxy dead: {is_dead} (See check_proxy_example.log for redacted logs)")

if __name__ == "__main__":
    asyncio.run(main())
