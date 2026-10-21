# Object-oriented programming in Python

## Classes and objects
A class is a blueprint; an object (instance) is one thing built from it. A `Dog` class describes what every dog has (data, called attributes) and can do (functions, called methods); `rex = Dog("Rex")` creates one dog.
```python
class Dog:
    def __init__(self, name):
        self.name = name        # attribute stored on this object

    def bark(self):             # method
        return f"{self.name} says woof"

rex = Dog("Rex")
print(rex.bark())               # Rex says woof
```
`__init__` runs automatically when an object is created and sets up its attributes. `self` is the object the method was called on; Python passes it for you, so `rex.bark()` becomes `Dog.bark(rex)`. Forgetting `self` as the first parameter gives `TypeError: ... takes 0 positional arguments but 1 was given`.

## Instance attributes and class attributes
Attributes set on `self` (`self.name`) belong to one object. Attributes defined directly in the class body are shared by all instances: `species = "Canis familiaris"`. Don't use a mutable class attribute such as `tricks = []` for per-object data, because every instance would share the same list; create it in `__init__` instead (`self.tricks = []`).

## Inheritance
A subclass reuses and extends a parent class: `class GuideDog(Dog):`. It inherits all of the parent's methods and can add new ones or override existing ones by defining a method with the same name. Call the parent's version with `super()`, for example `super().__init__(name)` inside the subclass's `__init__`. Use inheritance for a genuine "is a" relationship (a guide dog is a dog); for "has a" relationships (a car has an engine) store one object inside another instead (composition).

## Encapsulation, abstraction and polymorphism
Encapsulation keeps an object's data and the methods that work on it together, and hides internal details. Python marks internal attributes with a leading underscore by convention (`self._balance`); it doesn't enforce privacy. Abstraction means users work with a simple interface (`account.deposit(50)`) without knowing the implementation. Polymorphism means different classes respond to the same method call in their own way: `shape.area()` works whether `shape` is a `Circle` or a `Square`, as long as each class defines `area`.

## Special (dunder) methods
Methods with double underscores customise how objects behave with Python's syntax. `__str__` returns a readable string for `print(obj)`; `__repr__` returns an unambiguous one for debugging; `__eq__` defines `==` (by default, two objects are equal only if they are the same object); `__len__` makes `len(obj)` work; `__lt__` enables `<` and sorting. The `@dataclass` decorator from `dataclasses` writes `__init__`, `__repr__` and `__eq__` for simple data classes automatically.
