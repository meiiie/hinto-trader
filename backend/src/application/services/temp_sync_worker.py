
    # =========================================================================
    # BACKGROUND SYNC WORKER (SOTA)
    # Replaces usage of on-demand API calls for State Mirroring
    # =========================================================================

    async def start_background_sync(self):
        """Start background sync loop."""
        import asyncio
        if not self.client or self.mode == TradingMode.PAPER:
            return

        self._sync_task = asyncio.create_task(self._background_sync_loop())
        self.logger.info("🔄 Background Sync Worker started")

    async def _background_sync_loop(self):
        """
        Periodically sync state with Binance (Balance, Positions).

        SOTA: This is the ONLY place that should trigger 'get_portfolio' logic
        in a blocking manner (wrapped in thread). Frontend just reads cache.
        """
        import asyncio
        while True:
            try:
                if self.client:
                    # Offload blocking I/O to thread
                    await asyncio.to_thread(self._sync_local_cache)

            except Exception as e:
                self.logger.error(f"❌ Background sync failed: {e}")

            # Sync every 5 seconds (matching frontend poll rate)
            await asyncio.sleep(5)
