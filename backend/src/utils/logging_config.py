"""
Logging Configuration with Unicode Support
Handles Windows console encoding issues gracefully
"""

import sys
import io
import logging
import platform
from typing import Optional


def configure_logging(
    log_file: Optional[str] = None,
    level: int = logging.INFO,
    format_string: str = '%(asctime)s - %(levelname)s - %(message)s'
) -> logging.Logger:
    """
    Configure logging with Unicode support for Windows.

    Args:
        log_file: Path to log file (optional)
        level: Logging level (default: INFO)
        format_string: Log message format

    Returns:
        Configured logger instance

    Features:
        - UTF-8 encoding on Windows
        - Fallback to ASCII for console if UTF-8 fails
        - Emoji replacement for Windows console
        - Full Unicode support in log files
    """

    # Force UTF-8 encoding on Windows
    if platform.system() == 'Windows':
        try:
            # Try to set UTF-8 encoding for stdout/stderr
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding='utf-8',
                errors='replace'  # Replace unencodable characters
            )
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer,
                encoding='utf-8',
                errors='replace'
            )
        except Exception as e:
            # If UTF-8 fails, continue with default encoding
            print(f"Warning: Could not configure UTF-8 encoding: {e}")

    # Custom formatter with emoji fallback for Windows console
    class SafeFormatter(logging.Formatter):
        """Formatter that handles Unicode encoding errors gracefully"""

        # Emoji to ASCII mapping
        EMOJI_MAP = {
            '✅': '[OK]',
            '⚠️': '[WARN]',
            '❌': '[ERROR]',
            '🔄': '[SYNC]',
            '📊': '[DATA]',
            '🚀': '[START]',
            '⏸️': '[PAUSE]',
            '🎉': '[SUCCESS]',
            '💾': '[SAVE]',
            '🔍': '[CHECK]',
        }

        def format(self, record):
            """Format log record with emoji fallback"""
            try:
                # Try normal formatting
                return super().format(record)
            except UnicodeEncodeError:
                # Replace emojis with ASCII equivalents
                original_msg = record.msg
                for emoji, ascii_equiv in self.EMOJI_MAP.items():
                    if emoji in str(original_msg):
                        record.msg = str(original_msg).replace(emoji, ascii_equiv)

                try:
                    return super().format(record)
                except Exception:
                    # Last resort: remove all non-ASCII characters
                    record.msg = ''.join(
                        char for char in str(record.msg)
                        if ord(char) < 128
                    )
                    return super().format(record)

    # Create handlers
    handlers = []

    # File handler (full Unicode support)
    if log_file:
        file_handler = logging.FileHandler(
            log_file,
            encoding='utf-8',
            errors='replace'
        )
        file_handler.setFormatter(logging.Formatter(format_string))
        handlers.append(file_handler)

    # Console handler (with safe formatting)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(SafeFormatter(format_string))
    handlers.append(console_handler)

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=format_string,
        handlers=handlers,
        force=True  # Override any existing configuration
    )

    return logging.getLogger()


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Convenience function for quick setup
def setup_pipeline_logging(log_file: str) -> logging.Logger:
    """
    Setup logging specifically for the data pipeline.

    Args:
        log_file: Path to log file

    Returns:
        Configured logger
    """
    return configure_logging(
        log_file=log_file,
        level=logging.INFO,
        format_string='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
