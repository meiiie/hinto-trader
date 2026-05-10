"""
ValidateDataUseCase - Application Layer

Use case for validating market data quality.
"""

from typing import List, Dict
from ...domain.entities.market_data import MarketData
from ...domain.repositories.market_data_repository import MarketDataRepository


class ValidateDataUseCase:
    """Use case for validating data quality"""

    def __init__(self, repository: MarketDataRepository):
        self.repository = repository

    def execute(self, timeframe: str, limit: int = 100) -> Dict:
        """
        Validate data quality for a timeframe.

        Returns:
            Dictionary with validation results
        """
        # Get latest data
        market_data_list = self.repository.get_latest_candles(timeframe, limit)

        if not market_data_list:
            return {
                'status': 'NO_DATA',
                'record_count': 0,
                'issues': ['No data available']
            }

        # Validate each record
        issues = []
        valid_count = 0

        for market_data in market_data_list:
            is_valid, record_issues = market_data.validate()
            if is_valid:
                valid_count += 1
            else:
                issues.extend(record_issues)

        # Calculate quality score
        quality_score = (valid_count / len(market_data_list)) * 100

        return {
            'status': 'PASS' if quality_score >= 90 else 'FAIL',
            'record_count': len(market_data_list),
            'valid_count': valid_count,
            'quality_score': quality_score,
            'issues': issues[:10]  # Limit to 10 issues
        }
