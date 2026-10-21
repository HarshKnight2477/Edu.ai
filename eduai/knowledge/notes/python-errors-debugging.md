# Errors, debugging and files in Python

## Reading a traceback
When Python stops with an error it prints a traceback. Read it from the bottom up: the last line names the exception type and message (for example `TypeError: can only concatenate str (not "int") to str`); the lines above show the chain of calls, ending with the file and line number where the error happened. Go to that line first. The cause is often a line or two earlier, such as a variable that got the wrong value. Copy the exact error message when asking for help.

## Common Python exceptions and what they mean
- `SyntaxError`: the code is not valid Python (missing colon, unclosed bracket or quote). Python reports it before running anything.
- `IndentationError`: inconsistent indentation; use 4 spaces and don't mix tabs and spaces.
- `NameError`: a name is used before it was defined, or is misspelled.
- `TypeError`: an operation gets the wrong type, such as `"5" + 3` or calling something that isn't a function.
- `ValueError`: right type, wrong value, such as `int("abc")`.
- `IndexError`: list index out of range; remember the last index is `len(x) - 1`.
- `KeyError`: missing dictionary key; use `.get()` or check with `in`.
- `AttributeError`: the object has no such method or attribute, such as `"abc".reverse()`, since strings have no `reverse` method.
- `ZeroDivisionError`: division or modulo by zero.
- `RecursionError`: recursion went too deep, usually a missing or unreachable base case.

## Handling exceptions with try and except
Use `try`/`except` for errors you expect and can handle, such as bad user input:
```python
try:
    age = int(input("Age: "))
except ValueError:
    print("Please enter a whole number.")
```
Catch specific exceptions, not a bare `except:`, which also hides real bugs. `else` runs when no exception happened; `finally` always runs, which is useful for cleanup. `raise ValueError("message")` signals an error from your own code. Don't use exceptions to hide bugs: if a `TypeError` appears, fix the cause.

## A step-by-step debugging process
1. Reproduce the problem with the smallest input that fails.
2. Read the error message and traceback; find the exact line.
3. State what you expected and what actually happened.
4. Form a hypothesis about the cause, and test it: print variables at key points (`print(f"{i=} {total=}")`) or step through with a debugger (`breakpoint()` in Python 3.7+).
5. Fix one thing at a time, then re-run the failing case and the cases that already worked.
6. Add a test such as `assert average([2, 4, 6]) == 4` so the bug can't return.
Explaining the code line by line to someone, or to a rubber duck, often reveals the mistake.

## Common logic bugs in beginner code
- Off-by-one: `range(1, len(x))` skips index 0; `range(len(x) + 1)` goes past the end.
- Wrong starting value: finding a maximum with `max_val = 0` fails for all-negative lists; start with `nums[0]`.
- Case sensitivity: `"A" in "aeiou"` is `False`; normalise with `.lower()`.
- Integer division: `9 // 5` is 1, so `c * (9 // 5) + 32` converts temperatures wrongly; use `9 / 5`.
- Mutable default arguments: `def f(items=[])` shares one list between calls.
- Accumulator reset inside the loop, so the total keeps restarting.
- Using `=` (assignment) when you meant `==` (comparison); Python reports this as a SyntaxError inside an `if`.
- Forgetting to `return` a value, so the caller gets `None`.

## Reading and writing files
Open files with a `with` block, which closes the file automatically even if an error happens:
```python
with open("notes.txt", "r", encoding="utf-8") as f:
    for line in f:
        print(line.strip())
```
Modes: `"r"` read (the default; the file must exist), `"w"` write (creates the file or erases an existing one), `"a"` append, `"x"` create only if it doesn't exist; add `"b"` for binary. `f.read()` returns the whole file as one string, `f.readlines()` a list of lines. Lines keep their `"\n"`, so use `.strip()`. Write with `f.write(text)`, which does not add a newline for you. A missing file raises `FileNotFoundError`. Always pass `encoding="utf-8"` for text so the code works the same on Windows and Linux.
