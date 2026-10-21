# Python basics

## Variables and assignment
A variable is a name that refers to a value. `age = 18` creates the name `age` and makes it refer to the integer 18. The `=` sign means "assign", not "equals": `x = x + 1` takes the current value of `x`, adds 1, and stores the result back in `x`. Python decides the type from the value, so you never declare types: the same name can later refer to a string. Names may contain letters, digits and underscores, cannot start with a digit, and are case-sensitive (`Age` and `age` are different). Use descriptive names such as `total_price`. Assigning one variable to another (`b = a`) makes both names refer to the same object; it does not copy it.

## Data types
Python's core built-in types: `int` (whole numbers, any size), `float` (decimal numbers), `bool` (`True`/`False`), `str` (text), `None` (no value), and collections such as `list`, `tuple`, `dict` and `set`. Check a type with `type(x)` and convert with `int()`, `float()`, `str()`, `bool()`. Converting can fail: `int("3.5")` raises `ValueError`, while `int(3.9)` gives 3 because it cuts off the decimal part. `bool(0)`, `bool("")`, `bool([])` and `bool(None)` are all `False`; most other values are `True`.

## Numbers and arithmetic operators
Operators: `+`, `-`, `*`, `/` (true division, always a float: `7 / 2` is `3.5`), `//` (floor division: `7 // 2` is `3`, and `-7 // 2` is `-4` because it rounds down), `%` (remainder: `7 % 2` is `1`), `**` (power: `2 ** 3` is `8`). Floats are stored in binary, so some decimals are not exact: `0.1 + 0.2` gives `0.30000000000000004`. Compare floats with a tolerance, for example `abs(a - b) < 1e-9` or `math.isclose(a, b)`, instead of `==`. Use `round(x, 2)` for display.

## Strings
A string is an immutable sequence of characters: `name = "Asha"`. Index from 0 (`name[0]` is `"A"`) or from the end (`name[-1]` is `"a"`). Slicing `s[start:stop]` includes start and excludes stop: `"hello"[1:3]` is `"el"`; `s[::-1]` reverses a string. Strings cannot be changed in place; methods return new strings: `s.upper()`, `s.lower()`, `s.strip()` (removes whitespace from both ends only), `s.replace("a", "b")`, `s.split()`, `", ".join(words)`. f-strings format values: `f"{name} is {age} years old"` and `f"{price:.2f}"` for two decimals. `len(s)` gives the length; `"ell" in "hello"` tests for a substring.

## Input, output and type conversion
`print()` shows values: `print("Total:", total)` separates arguments with spaces; `print(x, end="")` avoids the newline. `input("Your name: ")` always returns a string, even if the user types digits, so convert it: `age = int(input("Age: "))`. If the user types something that isn't a number, `int()` raises `ValueError`; handle it with `try`/`except`. A very common beginner bug is adding a number read with `input()` without converting it: `"5" + "3"` is `"53"`, not 8.

## Booleans, comparisons and logical operators
Comparisons return `True` or `False`: `==`, `!=`, `<`, `>`, `<=`, `>=`. Combine conditions with `and`, `or`, `not`. Python evaluates them lazily (short-circuit): in `x != 0 and 10 / x > 1`, the division never runs when `x` is 0. `==` checks whether two values are equal; `is` checks whether two names refer to the same object. Use `is` only for `None` (`if x is None:`), and `==` for everything else. Chained comparisons work: `0 <= score <= 100`.

## Conditional statements (if, elif, else)
`if` runs a block only when its condition is true; `elif` checks further conditions in order; `else` runs when none matched. Only the first true branch runs. The block is defined by indentation (4 spaces is standard), and the line before it ends with a colon.
```python
if score >= 90:
    grade = "A"
elif score >= 75:
    grade = "B"
else:
    grade = "C"
```
Order matters: check the most specific condition first. For example, in FizzBuzz test `i % 15 == 0` before `i % 3 == 0`, otherwise multiples of 15 are caught by the "Fizz" branch.

## Loops: for, while, range, break and continue
A `for` loop repeats once per item: `for fruit in fruits:`. `range(stop)` produces 0 up to stop - 1; `range(start, stop, step)` includes start and excludes stop, so `range(2, 10, 3)` gives 2, 5, 8. Use `enumerate(items)` to get index and value together, and `zip(a, b)` to loop over two lists in parallel. A `while` loop repeats while a condition is true; make sure something inside changes the condition, or it loops forever. `break` leaves the loop immediately; `continue` skips to the next iteration. A classic off-by-one bug is `for i in range(1, len(nums))`, which skips the first element (index 0).

## Functions, parameters and return values
A function packages reusable code: `def area(width, height): return width * height`. Parameters are the names in the definition; arguments are the values you pass when calling. `return` sends a value back to the caller and ends the function; a function without `return` returns `None`. `print` only shows a value on screen; it does not give it back to the code that called the function, a frequent beginner confusion. Default values make parameters optional: `def greet(name, greeting="Hello"):`. Never use a mutable default like `items=[]`: the same list is reused across calls. Use `items=None` and create the list inside the function.

## Variable scope
Variables created inside a function are local: they exist only while the function runs and are invisible outside it. Variables defined at the top level of a file are global and can be read inside functions. Assigning to a name inside a function makes it local, so `count += 1` inside a function raises `UnboundLocalError` if `count` is a global. Prefer passing values in as parameters and returning results instead of using `global`, which makes code harder to follow and test.

## Recursion
A recursive function calls itself on a smaller version of the problem. Every recursive function needs a base case that returns without recursing, and each call must move toward it. Factorial: `factorial(0) = 1` (base case) and `factorial(n) = n * factorial(n - 1)`.
```python
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
```
Without a reachable base case the calls never stop and Python raises `RecursionError` (the default limit is about 1000 nested calls). Recursion suits naturally recursive structures such as trees, but a loop is often simpler and uses less memory for plain repetition.
