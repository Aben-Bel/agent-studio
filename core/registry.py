class Registry:
    def __init__(self, name):
        self.name = name
        self._items = {}

    def register(self, key):
        def deco(obj):
            self._items[key] = obj
            return obj
        return deco

    def get(self, key):
        if key not in self._items:
            raise KeyError(f"{self.name}: '{key}' not found. Have: {list(self._items)}")
        return self._items[key]

    def all(self):
        return dict(self._items)


AGENTS = Registry("agents")
TOOLS = Registry("tools")
SKILLS = Registry("skills")
