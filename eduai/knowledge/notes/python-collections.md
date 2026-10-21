# Python collections

## Lists
A list is an ordered, mutable collection: `nums = [3, 1, 4]`. Access by index (`nums[0]`), change items (`nums[1] = 10`), add with `append(x)` (one item at the end), `extend(other)` (all items of another list) or `insert(i, x)`, and remove with `remove(x)` (first matching value), `pop()` (last item, returned) or `pop(i)`. `len(nums)`, `sum(nums)`, `min()`, `max()` and `sorted(nums)` (returns a new sorted list) are built in; `nums.sort()` sorts in place and returns `None`, so `nums = nums.sort()` is a bug that sets `nums` to `None`. Checking `x in nums` scans the whole list, which is O(n).

## Tuples
A tuple is an ordered, immutable sequence: `point = (3, 4)`. You cannot add, remove or change items after creation, which makes tuples safe for fixed groups of values and allows them to be dictionary keys. A one-item tuple needs a comma: `(5,)`; `(5)` is just the number 5. Tuples support unpacking: `x, y = point`. Functions often return several values as a tuple: `return total, average`. Use a list when the collection will change, and a tuple for a fixed record.

## Dictionaries
A dictionary maps keys to values: `ages = {"Asha": 18, "Ravi": 20}`. Look up with `ages["Asha"]`; a missing key raises `KeyError`, while `ages.get("Sam")` returns `None` and `ages.get("Sam", 0)` returns 0. Add or update with `ages["Sam"] = 19`; delete with `del ages["Sam"]`. Loop over keys with `for name in ages`, or over pairs with `for name, age in ages.items()`. Keys must be immutable (strings, numbers, tuples). Lookup, insertion and deletion take O(1) time on average. Since Python 3.7, dictionaries remember insertion order. Counting pattern: `counts[w] = counts.get(w, 0) + 1`, or use `collections.Counter`.

## Sets
A set is an unordered collection of unique items: `colours = {"red", "green"}`. Adding a duplicate does nothing, so `set(items)` removes duplicates (but loses order). Membership tests (`x in s`) are O(1) on average, much faster than in a list. Set operations: union `a | b`, intersection `a & b`, difference `a - b`. An empty set is written `set()`, because `{}` creates an empty dictionary. To remove duplicates while keeping order, use `list(dict.fromkeys(items))`.

## List comprehensions
A list comprehension builds a list in one expression: `squares = [n * n for n in range(5)]` gives `[0, 1, 4, 9, 16]`. Add a filter with `if`: `evens = [n for n in nums if n % 2 == 0]`. The equivalent loop is:
```python
evens = []
for n in nums:
    if n % 2 == 0:
        evens.append(n)
```
Dictionary and set comprehensions work the same way: `{w: len(w) for w in words}`. Use comprehensions for simple transformations; switch to a normal loop when the logic needs several steps, so it stays readable.

## References, aliasing and copying
Variables hold references to objects. After `b = a` where `a` is a list, both names point to the same list, so `b.append(4)` also changes what you see through `a`. To get an independent copy use `a.copy()`, `list(a)` or `a[:]`. These are shallow copies: a list inside the list is still shared. For nested structures use `copy.deepcopy(a)`. Immutable objects (ints, strings, tuples) can be shared safely because they can't be changed. The same sharing happens when you pass a list to a function: the function can modify the caller's list.

## Modifying a list while iterating over it
Removing items from a list while looping over it skips elements, because the indexes shift under the loop. For example, removing duplicates with `for x in items: if ...: items.remove(x)` can leave duplicates behind. Instead, build a new list:
```python
unique = []
for x in items:
    if x not in unique:
        unique.append(x)
```
or loop over a copy (`for x in items[:]`), or use a comprehension: `[x for x in items if x != 0]`.
