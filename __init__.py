def classFactory(iface):
    from .locator import ListTasPlugin
    return ListTasPlugin(iface)