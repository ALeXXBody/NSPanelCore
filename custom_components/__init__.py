# Namespace shim: lets Home Assistant's loader (and the test harness)
# discover integrations from BOTH this repo's custom_components and the
# pytest plugin's testing_config copies.
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
