async def test_debug_discovery(hass, enable_custom_integrations):
    import custom_components, os
    print("custom_components __path__:", list(custom_components.__path__))
    print("contents:", os.listdir(custom_components.__path__[0]))
    from homeassistant.loader import _get_custom_components
    comps = _get_custom_components(hass)
    print("direct discovery:", list(comps))
