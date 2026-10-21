# C, C++, Java and SQL basics

## C language basics compared with Python
C is compiled: you turn source code into a program with a compiler (`gcc hello.c -o hello`) before running it, and errors are reported at compile time. Every variable has a declared, fixed type (`int count = 0; double price = 9.5; char letter = 'A';`). Statements end with semicolons and blocks use braces `{ }`, not indentation. Every program starts in `main`:
```c
#include <stdio.h>

int main(void) {
    int age = 18;
    printf("Age: %d\n", age);   /* %d int, %f double, %s string, %c char */
    return 0;
}
```
Integer division truncates toward zero: `7 / 2` is 3 and `-7 / 2` is -3; use `7.0 / 2` for 3.5. Read input with `scanf("%d", &age);`, where the `&` passes the variable's address.

## C arrays, strings, pointers and memory
C arrays have a fixed size and no bounds checking: `int nums[5];` has valid indexes 0 to 4, and writing `nums[5]` corrupts memory silently instead of raising an error. Strings are arrays of `char` ending with the null character `'\0'`, so `"cat"` needs 4 bytes; compare strings with `strcmp`, not `==`. A pointer stores a memory address: `int *p = &x;` and `*p` reads the value at that address. Memory from `malloc` must be released with `free`, otherwise the program leaks memory; using memory after freeing it is undefined behaviour. These manual details are a major difference from Python, which manages memory automatically.

## C++ basics
C++ extends C with classes, references, templates and the Standard Library. Print with `std::cout << "Hi " << name << std::endl;` from `<iostream>`, and read with `std::cin >> x;`. Prefer `std::string` over C character arrays, and `std::vector<int>` (a resizable array: `push_back`, `size()`, bounds-checked `at()`) over raw arrays. Classes bundle data and methods like Python classes, with `public:`/`private:` access control enforced by the compiler. Range-based loops: `for (int x : nums) { ... }`. Integer division truncates toward zero as in C.

## Java basics
In Java, all code lives inside classes, and a program starts at `public static void main(String[] args)`. Types are declared and checked at compile time (`int`, `double`, `boolean`, `char`, `String`). Print with `System.out.println("Hello");`. Compile with `javac Main.java` and run with `java Main`.
```java
public class Main {
    public static void main(String[] args) {
        int total = 7 / 2;          // 3: integer division
        System.out.println(total);
    }
}
```
Use `ArrayList<Integer>` for resizable lists and `HashMap<String, Integer>` for key-value maps. Compare strings with `.equals()`, not `==`, which compares object identity. Java manages memory with a garbage collector, like Python.

## SQL basics: querying tables
SQL queries data in relational tables. `SELECT name, age FROM students WHERE age >= 18 ORDER BY name;` picks columns, filters rows, then sorts. `WHERE` filters individual rows before grouping; `GROUP BY` groups rows; aggregate functions (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`) summarise each group; `HAVING` filters groups after aggregation:
```sql
SELECT class, AVG(score) AS avg_score
FROM results
WHERE year = 2026
GROUP BY class
HAVING AVG(score) > 70;
```
`INNER JOIN` keeps only rows that match in both tables; `LEFT JOIN` keeps every row from the left table and fills missing matches with `NULL`. Test for missing values with `IS NULL`, not `= NULL`. Modify data with `INSERT`, `UPDATE` and `DELETE`; an `UPDATE` or `DELETE` without `WHERE` affects every row.
