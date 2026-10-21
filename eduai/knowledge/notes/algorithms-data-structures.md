# Algorithms and data structures

## Time complexity and Big-O notation
Big-O describes how an algorithm's running time (or memory) grows as the input size n grows, ignoring constant factors. Common classes, from fastest to slowest: O(1) constant (dictionary lookup), O(log n) logarithmic (binary search), O(n) linear (scanning a list), O(n log n) (efficient sorting), O(n²) quadratic (nested loops over the same data), O(2ⁿ) exponential (trying every subset). Big-O usually states the worst case. Doubling n barely changes O(log n), doubles O(n) and quadruples O(n²). Space complexity measures extra memory in the same way.

## Linear search and binary search
Linear search checks items one by one: O(n), works on any list. Binary search works only on a sorted list: compare the target with the middle item, then discard the half that can't contain it, repeating until found or the range is empty. That is O(log n): about 20 steps for a million items.
```python
def binary_search(arr, target):
    low, high = 0, len(arr) - 1
    while low <= high:              # <= so a one-item range is still checked
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
```
Common bugs: using `while low < high` (misses the last remaining item) and updating `low = mid` instead of `mid + 1` (can loop forever).

## Sorting algorithms compared
- Bubble sort: repeatedly swaps adjacent out-of-order items. O(n²) average and worst; O(n) best if it stops when no swaps happen. Stable.
- Selection sort: repeatedly selects the smallest remaining item and moves it into place. O(n²) always. Not stable.
- Insertion sort: inserts each item into the sorted part on its left. O(n²) worst, O(n) on nearly sorted data. Stable; good for small inputs.
- Merge sort: splits the list in half, sorts each half recursively, and merges them. O(n log n) always; stable; needs O(n) extra memory.
- Quicksort: picks a pivot, partitions into smaller and larger items, and sorts each side recursively. O(n log n) on average, O(n²) worst case (consistently bad pivots, such as the first element of already sorted data). Usually fast in practice; the in-place version is not stable.
Stable means equal items keep their original order. Python's `sorted()` and `list.sort()` use Timsort: O(n log n) worst case and stable. In real code, use them instead of writing your own.

## Stacks and queues
A stack is Last-In, First-Out (LIFO), like a pile of plates: push onto the top, pop from the top. In Python use a list: `append()` and `pop()` are O(1). Stacks power undo features, bracket matching and function calls (the call stack). A queue is First-In, First-Out (FIFO), like a line at a shop: add at the back, remove from the front. Use `collections.deque` with `append()` and `popleft()`, both O(1); `list.pop(0)` is O(n) because every other item shifts.

## Linked lists
A linked list stores items in nodes; each node holds a value and a reference to the next node. Inserting or removing at the front is O(1) and needs no shifting, but finding the k-th item means walking from the start: O(n), unlike a Python list's O(1) indexing. Doubly linked lists also point backwards. Python's built-in list is a dynamic array, not a linked list; linked lists are mostly studied to understand references and pointers.

## Hash tables
A hash table stores key-value pairs. A hash function turns each key into an index in an array, so lookup, insertion and deletion take O(1) time on average. When two keys land on the same index (a collision), the table resolves it, for example by keeping a small list at that slot; heavy collisions degrade towards O(n). Python's `dict` and `set` are hash tables, which is why their keys must be hashable (immutable): strings, numbers and tuples, but not lists.

## Trees and binary search trees
A tree is a hierarchy of nodes: one root, each node with children, and leaves with no children. In a binary tree each node has at most two children. In a binary search tree (BST), everything in a node's left subtree is smaller and everything in the right subtree is larger, so search, insert and delete take O(log n) when the tree is balanced, but O(n) if it degenerates into a line (for example, inserting already sorted values). Traversals: in-order (left, node, right) visits a BST in sorted order; pre-order and post-order are also common. File systems and HTML pages are trees.

## Graphs, BFS and DFS
A graph is a set of nodes (vertices) connected by edges, which may be directed and/or weighted. Store it as an adjacency list, such as a dict mapping each node to its neighbours. Breadth-first search (BFS) explores level by level using a queue and finds the shortest path, in number of edges, in an unweighted graph. Depth-first search (DFS) goes as deep as possible before backtracking, using a stack or recursion; it is useful for detecting cycles and exploring connected components. Both run in O(V + E) and must track visited nodes to avoid looping forever. For weighted shortest paths, use Dijkstra's algorithm (non-negative weights).

## Recursion versus iteration, and dynamic programming
Any recursive solution can be written as a loop, and vice versa. Recursion is natural for trees and divide-and-conquer (merge sort), but each call uses stack memory. Naive recursion can repeat work: computing Fibonacci recursively takes exponential time because the same values are recomputed. Dynamic programming fixes this by storing results of subproblems, either top-down with memoisation (`functools.lru_cache`) or bottom-up by filling a table, which turns Fibonacci into O(n). It applies when a problem has overlapping subproblems and its optimal solution is built from optimal sub-solutions.
