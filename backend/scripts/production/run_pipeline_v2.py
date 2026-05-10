"""
Main entry point to run the Binance Data Pipeline (Version 2 - Clean Architecture).

This script uses the new Clean Architecture with DI Container.
Data will be fetched every 15 minutes.
"""

import sys
import os
import logging
from apscheduler.schedulers.blocking import BlockingScheduler

# Add parent directory to path to import src modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.infrastructure.di_container import DIContainer
from src.utils.logging_config import configure_logging


def main():
    """Main function to run the pipeline with Clean Architecture."""
    print("=" * 60)
    print("Binance Data Pipeline (Clean Architecture)")
    print("=" * 60)
    print()

    # Setup logging
    configure_logging(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        # Initialize DI Container
        config = {
            'DATABASE_PATH': 'crypto_data.db',
            'BINANCE_API_KEY': None,  # Not needed for public endpoints
            'BINANCE_API_SECRET': None
        }

        container = DIContainer(config)
        logger.info("DI Container initialized")

        # Get PipelineService
        pipeline_service = container.get_pipeline_service()
        logger.info("PipelineService created")

        def run_update():
            """Run pipeline update for both timeframes"""
            logger.info("Starting scheduled update...")

            # Update 15m data
            result_15m = pipeline_service.update_market_data(
                symbol='BTCUSDT',
                timeframe='15m',
                limit=5
            )
            logger.info(f"15m update: {result_15m['message']}")

            # Update 1h data
            result_1h = pipeline_service.update_market_data(
                symbol='BTCUSDT',
                timeframe='1h',
                limit=5
            )
            logger.info(f"1h update: {result_1h['message']}")

            # Show status
            status = pipeline_service.get_pipeline_status()
            logger.info(f"Pipeline status: {status['status']}")
            logger.info(f"Database size: {status['database_size_mb']:.2f} MB")

        # Create scheduler
        scheduler = BlockingScheduler()

        # Add scheduled job - run every 15 minutes
        scheduler.add_job(
            run_update,
            'interval',
            minutes=15,
            id='update_data_job',
            name='Update cryptocurrency data'
        )

        logger.info("Scheduler configured - updates every 15 minutes")
        logger.info("Press Ctrl+C to stop")

        # Run immediately on start
        logger.info("Running initial update...")
        run_update()

        # Start scheduler (blocking)
        logger.info("Starting scheduler...")
        scheduler.start()

    except KeyboardInterrupt:
        logger.info("Pipeline stopped by user (Ctrl+C)")
        print("\n\nPipeline stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    finally:
        # Cleanup
        if 'container' in locals():
            container.cleanup()
            logger.info("Container cleaned up")


if __name__ == "__main__":
    main()
