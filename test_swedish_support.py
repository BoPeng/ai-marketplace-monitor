#!/usr/bin/env python3
"""Test script for Swedish language support in AI Marketplace Monitor."""

import os
import tempfile
from pathlib import Path

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.utils import Translator


def test_swedish_translations() -> None:
    """Test that Swedish translations are loaded correctly."""
    # Create a minimal config with Swedish translation
    config_content = """
[translation.sv]
locale = "Swedish"
'Condition' = 'Skick'
'Description' = 'Beskrivning'
'Details' = 'Detaljer'
'Location is approximate' = 'Platsen är ungefärlig'
"About this vehicle" = "Om detta fordon"
"Seller's description" = "Säljarens beskrivning"

[marketplace.facebook]
search_city = 'Stockholm'
username = 'test'
password = 'test'
language = 'sv'

[ai.openai]
api_key = 'test'
model = 'gpt-4o'

[user.test]
email = 'test@example.com'

[item.test]
search_phrases = 'test'
"""

    # Write config to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        config_path = f.name

    try:
        # Load config
        config = Config([Path(config_path)], None)

        # Test that Swedish translator is loaded
        assert "sv" in config.translator, "Swedish translator not found in config"

        sv_translator = config.translator["sv"]
        assert isinstance(
            sv_translator, Translator
        ), "Swedish translator is not a Translator instance"
        assert (
            sv_translator.locale == "Swedish"
        ), f"Expected locale 'Swedish', got '{sv_translator.locale}'"

        # Test translations
        test_cases = [
            ("Condition", "Skick"),
            ("Description", "Beskrivning"),
            ("Details", "Detaljer"),
            ("Location is approximate", "Platsen är ungefärlig"),
            ("About this vehicle", "Om detta fordon"),
            ("Seller's description", "Säljarens beskrivning"),
        ]

        for english, expected_swedish in test_cases:
            translated = sv_translator(english)
            assert (
                translated == expected_swedish
            ), f"Translation failed: '{english}' -> '{translated}', expected '{expected_swedish}'"

        # Test that untranslated text returns as-is
        untranslated = sv_translator("This text is not translated")
        assert (
            untranslated == "This text is not translated"
        ), "Untranslated text should return as-is"

        print("✅ All Swedish translation tests passed!")

        # Test marketplace config with Swedish language
        facebook_config = config.marketplace["facebook"]
        assert (
            facebook_config.language == "sv"
        ), f"Expected language 'sv', got '{facebook_config.language}'"

        print("✅ Swedish language configuration test passed!")

    finally:
        # Clean up
        os.unlink(config_path)


def test_swedish_marketplace_integration() -> None:
    """Test that Swedish language is properly integrated with marketplace config."""
    config_content = """
[translation.sv]
locale = "Swedish"
'Condition' = 'Skick'

[marketplace.facebook]
search_city = 'Stockholm'
username = 'test'
password = 'test'
language = 'sv'

[ai.openai]
api_key = 'test'
model = 'gpt-4o'

[user.test]
email = 'test@example.com'

[item.test]
search_phrases = 'test'
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        config_path = f.name

    try:
        config = Config([Path(config_path)], None)

        # Verify that the marketplace configuration includes Swedish language
        facebook_config = config.marketplace["facebook"]
        assert hasattr(
            facebook_config, "language"
        ), "Marketplace config should have language attribute"
        assert facebook_config.language == "sv", "Language should be set to 'sv'"

        print("✅ Swedish marketplace integration test passed!")

    finally:
        os.unlink(config_path)


if __name__ == "__main__":
    print("Testing Swedish language support...")
    test_swedish_translations()
    test_swedish_marketplace_integration()
    print("🎉 All tests passed! Swedish language support is working correctly.")
