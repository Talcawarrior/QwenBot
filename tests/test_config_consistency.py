"""Tests for config/settings consistency checks."""


def test_import_config_settings_does_not_raise():
    """assert_config_consistency() must pass at import time."""
    # This raises RuntimeError if KELLY_FRACTION or FEE_DRAG
    # do not match bot_config.strategy values.
    import config.settings  # noqa: F401


def test_strategy_config_min_edge_default():
    """bot_config.strategy.min_edge should be 0.05 (5% edge floor)."""
    from config.settings import bot_config
    assert bot_config.strategy.min_edge == 0.05, (
        f"Expected min_edge=0.05, got {bot_config.strategy.min_edge}"
    )


def test_config_fee_drag_matches_strategy():
    """Config.FEE_DRAG should equal bot_config.strategy.fee_drag."""
    from config.settings import bot_config, config
    assert config.FEE_DRAG == bot_config.strategy.fee_drag, (
        f"FEE_DRAG={config.FEE_DRAG} != strategy.fee_drag={bot_config.strategy.fee_drag}"
    )


def test_config_kelly_fraction_matches_strategy():
    """Config.KELLY_FRACTION should equal bot_config.strategy.kelly_fraction."""
    from config.settings import bot_config, config
    assert config.KELLY_FRACTION == bot_config.strategy.kelly_fraction, (
        f"KELLY_FRACTION={config.KELLY_FRACTION} != "
        f"strategy.kelly_fraction={bot_config.strategy.kelly_fraction}"
    )
