print("Starting import...")
try:
    import sys
    print(f"Python path: {sys.path}")
    from src.infrastructure.indicators.talib_calculator import TALibCalculator
    print("Import successful")
    calc = TALibCalculator()
    print("Instantiation successful")
except Exception as e:
    print(f"Error: {e}")
