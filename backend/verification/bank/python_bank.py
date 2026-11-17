"""
Python question bank (41 questions: 12 easy / 15 medium / 14 hard).

Each question is tagged with a category (fundamentals, code_reading, debugging,
problem_solving, implementation), a concept, optional prerequisite concepts
(used by the adaptive engine to probe fundamentals after a miss) and a
difficulty. An assessment draws only 8-12 of these, so the bank is ~3.5x larger
than what any single candidate sees.

Question types
  mcq / scenario : single answer, options are shuffled per attempt
  output         : candidate types exactly what the snippet prints
  code           : implement a function; graded by hidden unit tests in the sandbox
  debug          : fix a buggy function; graded by hidden unit tests in the sandbox

`reference` solutions and `wrong` solutions exist ONLY so tests/test_bank.py can
prove every question is answerable and every test-suite discriminates. They are
never sent to a client.
"""

SKILL = "python"


def _fb(n):
    out = []
    for i in range(1, n + 1):
        out.append("FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i))
    return out


def _min_coins(coins, amount):
    inf = float("inf")
    dp = [0] + [inf] * amount
    for a in range(1, amount + 1):
        for c in coins:
            if c <= a and dp[a - c] + 1 < dp[a]:
                dp[a] = dp[a - c] + 1
    return -1 if dp[amount] == inf else dp[amount]


def _nested(depth):
    x = [1]
    for _ in range(depth):
        x = [x]
    return x


_CJK = "".join(chr(0x4E00 + i) for i in range(20000))


def _two_sum_big():
    nums = list(range(1, 2001))
    nums[-1], nums[-2] = 4000001, 3000001  # unique pair at the very end
    return nums, 7000002


_TS_BIG, _TS_TARGET = _two_sum_big()


def _topk_expected(words, k):
    from collections import Counter
    c = Counter(words)
    return [w for w, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


_TOPK_WORDS = ["w%d" % (i % 997) for i in range(300000)]


def mcq(id, category, difficulty, concept, prompt, options, answer, explanation, *, code=None, prereqs=(),
        type="mcq", time_hint_s=60):
    return {"id": id, "skill": SKILL, "category": category, "difficulty": difficulty, "concept": concept,
            "prereqs": list(prereqs), "type": type, "prompt": prompt, "code": code, "options": options,
            "answer": answer, "explanation": explanation, "time_hint_s": time_hint_s}


def output(id, difficulty, concept, code, expected, explanation, *, prereqs=(), prompt=None, time_hint_s=75):
    return {"id": id, "skill": SKILL, "category": "code_reading", "difficulty": difficulty, "concept": concept,
            "prereqs": list(prereqs), "type": "output",
            "prompt": prompt or "What does this program print? Type the output exactly as it appears.",
            "code": code, "expected": expected, "explanation": explanation, "time_hint_s": time_hint_s}


def code(id, category, difficulty, concept, prompt, func, starter, tests, reference, explanation, *,
         prereqs=(), wrong=(), type="code", time_hint_s=300):
    return {"id": id, "skill": SKILL, "category": category, "difficulty": difficulty, "concept": concept,
            "prereqs": list(prereqs), "type": type, "prompt": prompt, "func": func, "starter": starter,
            "tests": tests, "reference": reference, "wrong": list(wrong), "explanation": explanation,
            "time_hint_s": time_hint_s}


def T(args, expected, visible=False, **kw):
    t = {"args": args, "expected": expected, "visible": visible}
    t.update(kw)
    return t


QUESTIONS = [
    # =====================================================================
    # EASY (12)
    # =====================================================================
    mcq("py-f-e1", "fundamentals", "easy", "numeric_types",
        "What is the value and type of the expression `7 / 2` in Python 3?",
        ["3 (int)", "3.5 (float)", "3.0 (float)", "4 (int)"], 1,
        "In Python 3 the `/` operator always performs true division and returns a float, so 7 / 2 is 3.5. "
        "Use `//` for floor division (7 // 2 == 3)."),
    mcq("py-f-e2", "fundamentals", "easy", "mutability",
        "Which of these built-in types is immutable?",
        ["list", "dict", "set", "tuple"], 3,
        "Tuples cannot be changed after creation. Lists, dicts and sets are mutable, which matters for "
        "aliasing, default arguments and using values as dictionary keys."),
    mcq("py-f-e3", "fundamentals", "easy", "dict_methods",
        "Given `d = {'a': 1}`, what does `d.get('b', 0)` return?",
        ["It raises KeyError", "None", "0", "1"], 2,
        "`dict.get(key, default)` returns the default instead of raising KeyError when the key is missing. "
        "Without a default, get() returns None."),

    output("py-c-e1", "easy", "slicing", 'print("hello"[1:4])', "ell",
           "Slices include the start index and exclude the stop index: characters at positions 1, 2 and 3 are 'e', 'l', 'l'."),
    output("py-c-e2", "easy", "aliasing",
           "x = [1, 2, 3]\ny = x\ny.append(4)\nprint(len(x))", "4",
           "`y = x` does not copy the list; both names refer to the same object, so appending through y changes x too.",
           prereqs=["mutability"]),
    output("py-c-e3", "easy", "range_loops",
           'for i in range(3):\n    print(i * 2, end=" ")', "0 2 4",
           "range(3) yields 0, 1, 2. Each value is doubled and printed followed by a space instead of a newline."),

    mcq("py-d-e1", "debugging", "easy", "assignment_vs_equality",
        "What happens when this code is run?",
        ["It prints five", "SyntaxError", "NameError", "It prints nothing"], 1,
        "A single `=` is assignment and cannot be used as a condition. Python reports a SyntaxError; the intended "
        "comparison operator is `==`.",
        code="x = 5\nif x = 5:\n    print(\"five\")"),
    mcq("py-d-e2", "debugging", "easy", "scope_basics",
        "What happens when this program runs?",
        ["It prints Hi", "NameError", "TypeError", "It prints None"], 1,
        "`message` is a local variable of greet() and greet is never even called. At module level the name `message` "
        "does not exist, so Python raises NameError.",
        code="def greet(name):\n    message = \"Hi \" + name\n\nprint(message)"),

    code("py-p-e1", "problem_solving", "easy", "control_flow",
         "Write `fizzbuzz(n)` that returns a list of strings for the numbers 1..n: \"Fizz\" for multiples of 3, "
         "\"Buzz\" for multiples of 5, \"FizzBuzz\" for multiples of both, otherwise the number as a string. "
         "`fizzbuzz(0)` returns an empty list.",
         "fizzbuzz", "def fizzbuzz(n):\n    # return a list of strings for 1..n\n    pass\n",
         [T([5], _fb(5), True), T([1], ["1"], True), T([15], _fb(15)), T([0], []), T([30], _fb(30)), T([3], _fb(3))],
         "def fizzbuzz(n):\n    out = []\n    for i in range(1, n + 1):\n        if i % 15 == 0:\n            out.append('FizzBuzz')\n"
         "        elif i % 3 == 0:\n            out.append('Fizz')\n        elif i % 5 == 0:\n            out.append('Buzz')\n"
         "        else:\n            out.append(str(i))\n    return out\n",
         "Check the combined case (multiples of 15) before the individual ones, otherwise 15 becomes just 'Fizz'.",
         wrong=["def fizzbuzz(n):\n    return [str(i) for i in range(n)]\n"]),
    code("py-p-e2", "problem_solving", "easy", "string_split",
         "Write `reverse_words(sentence)` that returns the words of the sentence in reverse order, separated by a "
         "single space. Ignore leading, trailing and repeated spaces.",
         "reverse_words", "def reverse_words(sentence):\n    pass\n",
         [T(["hello big world"], "world big hello", True), T(["one two"], "two one", True),
          T(["  a   b  "], "b a"), T([""], ""), T(["single"], "single"), T(["x y z w"], "w z y x")],
         "def reverse_words(sentence):\n    return ' '.join(reversed(sentence.split()))\n",
         "`str.split()` with no arguments splits on any run of whitespace and drops empty strings, which handles the extra spaces.",
         wrong=["def reverse_words(sentence):\n    return ' '.join(sentence.split(' ')[::-1])\n"]),

    code("py-i-e1", "implementation", "easy", "string_iteration",
         "Write `count_vowels(s)` that returns how many vowels (a, e, i, o, u - upper or lower case) the string contains. "
         "The letter y is not a vowel.",
         "count_vowels", "def count_vowels(s):\n    pass\n",
         [T(["hello"], 2, True), T(["RHYTHM"], 0, True), T([""], 0), T(["AEIOUaeiou"], 10),
          T(["Python Programming"], 4), T(["sky"], 0)],
         "def count_vowels(s):\n    return sum(1 for ch in s.lower() if ch in 'aeiou')\n",
         "Lower-case the string once and test membership in 'aeiou' for each character.",
         wrong=["def count_vowels(s):\n    return sum(1 for ch in s if ch in 'aeiou')\n"]),
    code("py-i-e2", "implementation", "easy", "loops_conditionals",
         "Write `sum_of_evens(nums)` that returns the sum of the even integers in a list. An empty list gives 0.",
         "sum_of_evens", "def sum_of_evens(nums):\n    pass\n",
         [T([[1, 2, 3, 4]], 6, True), T([[]], 0, True), T([[-2, -3, 4]], 2), T([[7]], 0), T([[0, 0]], 0),
          T([list(range(1, 101))], 2550)],
         "def sum_of_evens(nums):\n    return sum(n for n in nums if n % 2 == 0)\n",
         "`n % 2 == 0` is also correct for negative numbers in Python because the result of % takes the sign of the divisor.",
         wrong=["def sum_of_evens(nums):\n    return sum(n for n in nums if n % 2 == 1)\n"]),

    # =====================================================================
    # MEDIUM (15)
    # =====================================================================
    mcq("py-f-m1", "fundamentals", "medium", "identity_vs_equality",
        "Which statement about `==` and `is` in Python is correct?",
        ["`==` compares object identity and `is` compares values",
         "`==` compares values and `is` checks whether two names refer to the same object",
         "They are interchangeable for lists but not for numbers",
         "`is` is simply a faster spelling of `==`"], 1,
        "`==` asks whether two objects are equal in value; `is` asks whether they are literally the same object in memory. "
        "Two equal lists built separately are `==` but not `is`.", prereqs=["mutability"]),
    mcq("py-f-m2", "fundamentals", "medium", "data_structure_choice",
        "You must store about 1,000,000 unique user IDs and check very frequently whether a given ID is present. "
        "Which built-in structure is the best fit?",
        ["list, because it keeps insertion order",
         "set, because membership tests are O(1) on average",
         "tuple, because it is immutable and therefore fast",
         "str, joining the IDs with commas"], 1,
        "Sets (and dicts) are hash tables, so `x in s` is O(1) on average. Membership in a list is O(n) because every element may be compared.",
        type="scenario", prereqs=["dict_methods", "mutability"]),
    mcq("py-f-m3", "fundamentals", "medium", "generators_vs_lists",
        "What is the key difference between `[x*x for x in range(5)]` and `(x*x for x in range(5))`?",
        ["The first is a list built immediately; the second is a lazy generator that produces values on demand",
         "The first is lazy and the second builds a list immediately",
         "Both build full lists; only the brackets differ",
         "The second form is a syntax error"], 0,
        "Square brackets build the whole list in memory. Parentheses create a generator expression that yields one value at a time, "
        "which saves memory and can be consumed only once.", prereqs=["range_loops"]),

    output("py-c-m1", "medium", "mutable_default_args",
           "def add_item(item, bucket=[]):\n    bucket.append(item)\n    return bucket\n\nadd_item(1)\nprint(add_item(2))",
           "[1, 2]",
           "The default list is created once, when the function is defined, and shared by every call that omits the argument. "
           "The second call therefore sees the 1 appended by the first.", prereqs=["mutability", "aliasing"]),
    output("py-c-m2", "medium", "sorted_vs_sort",
           "nums = [3, 1, 2]\nresult = sorted(nums)\nnums.sort(reverse=True)\nprint(result, nums)",
           "[1, 2, 3] [3, 2, 1]",
           "`sorted()` returns a new list and leaves the original alone; `list.sort()` sorts in place (and returns None).",
           prereqs=["mutability"]),
    output("py-c-m3", "medium", "dict_counting",
           'd = {}\nfor w in "banana":\n    d[w] = d.get(w, 0) + 1\nprint(sorted(d.items()))',
           "[('a', 3), ('b', 1), ('n', 2)]",
           "The loop counts characters: a appears 3 times, b once and n twice. `sorted()` on the (key, value) pairs orders them by key.",
           prereqs=["dict_methods"]),

    mcq("py-d-m3", "debugging", "medium", "mutating_while_iterating",
        "This code is meant to remove every even number, but it prints `[4]`. Why?",
        ["`remove` only works on the last element of a list",
         "Removing items while iterating shifts the remaining elements, so the loop skips some of them",
         "`x % 2 == 0` is False for the number 4",
         "Lists cannot be modified inside a for loop at all - it should raise an error"], 1,
        "When 2 is removed, the list shrinks to [4, 6] and the loop's internal index moves on to the next position, skipping 4. "
        "Iterate over a copy (`for x in items[:]`) or build a new list with a comprehension instead.",
        code="items = [2, 4, 6]\nfor x in items:\n    if x % 2 == 0:\n        items.remove(x)\nprint(items)",
        prereqs=["aliasing", "range_loops"]),
    code("py-d-m1", "debugging", "medium", "logic_errors",
         "The function below should return the items without duplicates, keeping the order in which each item first appears. "
         "It has a bug. Fix it so that `remove_duplicates([1, 2, 1, 3, 2])` returns `[1, 2, 3]`.",
         "remove_duplicates",
         "def remove_duplicates(items):\n    seen = set()\n    result = []\n    for item in items:\n        if item in seen:\n"
         "            result.append(item)\n        seen.add(item)\n    return result\n",
         [T([[1, 2, 1, 3, 2]], [1, 2, 3], True), T([["a", "b", "a"]], ["a", "b"], True), T([[]], []),
          T([[1, 1, 1]], [1]), T([[3, 2, 1]], [3, 2, 1]), T([list(range(500)) * 2], list(range(500)))],
         "def remove_duplicates(items):\n    seen = set()\n    result = []\n    for item in items:\n        if item not in seen:\n"
         "            result.append(item)\n        seen.add(item)\n    return result\n",
         "The condition was inverted: an item should be appended the FIRST time it is seen, i.e. when it is NOT in `seen`.",
         type="debug", prereqs=["loops_conditionals"],
         wrong=["def remove_duplicates(items):\n    return list(set(items))\n"]),
    code("py-d-m2", "debugging", "medium", "off_by_one",
         "`moving_sum(nums, k)` should return the sum of every window of k consecutive numbers, e.g. "
         "`moving_sum([1, 2, 3, 4], 2)` is `[3, 5, 7]`. It returns the wrong result. Fix it.",
         "moving_sum",
         "def moving_sum(nums, k):\n    result = []\n    for i in range(len(nums) - k):\n        result.append(sum(nums[i:i + k]))\n    return result\n",
         [T([[1, 2, 3, 4], 2], [3, 5, 7], True), T([[1, 2], 3], [], True), T([[5], 1], [5]), T([[1, 2, 3], 3], [6]),
          T([[4, 4, 4, 4], 1], [4, 4, 4, 4]), T([[], 2], [])],
         "def moving_sum(nums, k):\n    result = []\n    for i in range(len(nums) - k + 1):\n        result.append(sum(nums[i:i + k]))\n    return result\n",
         "There are len(nums) - k + 1 windows. The original range stops one window short (an off-by-one error).",
         type="debug", prereqs=["range_loops", "slicing"]),

    code("py-p-m1", "problem_solving", "medium", "hash_lookup",
         "Write `two_sum_indices(nums, target)`. There is at most one pair of positions i < j with "
         "`nums[i] + nums[j] == target`. Return `[i, j]`, or `[]` if no such pair exists.",
         "two_sum_indices", "def two_sum_indices(nums, target):\n    pass\n",
         [T([[2, 7, 11, 15], 9], [0, 1], True), T([[1, 2, 3], 10], [], True), T([[3, 2, 4], 6], [1, 2]),
          T([[3, 3], 6], [0, 1]), T([[], 5], []), T([[5], 5], []), T([[0, 4, 3, 0], 0], [0, 3]),
          T([[-3, 4, 3, 90], 0], [0, 2]), T([_TS_BIG, _TS_TARGET], [1998, 1999])],
         "def two_sum_indices(nums, target):\n    seen = {}\n    for j, n in enumerate(nums):\n        if target - n in seen:\n"
         "            return [seen[target - n], j]\n        seen[n] = j\n    return []\n",
         "Store each number's index in a dict while scanning; if target - n has been seen, you have the pair in one pass (O(n)). "
         "A nested loop also works for small inputs but is O(n^2).",
         prereqs=["dict_methods", "loops_conditionals"],
         wrong=["def two_sum_indices(nums, target):\n    for i in range(len(nums)):\n        for j in range(len(nums)):\n"
                "            if nums[i] + nums[j] == target:\n                return [i, j]\n    return []\n"]),
    code("py-p-m2", "problem_solving", "medium", "string_normalization",
         "Write `is_palindrome(s)` that returns True if the string reads the same forwards and backwards when you ignore "
         "case and every character that is not a letter or digit. The empty string is a palindrome.",
         "is_palindrome", "def is_palindrome(s):\n    pass\n",
         [T(["A man, a plan, a canal: Panama"], True, True), T(["race a car"], False, True), T([""], True),
          T([" "], True), T(["0P"], False), T(["Was it a car or a cat I saw?"], True), T(["ab"], False),
          T(["No 'x' in Nixon"], True)],
         "def is_palindrome(s):\n    t = [c.lower() for c in s if c.isalnum()]\n    return t == t[::-1]\n",
         "Normalise first (keep alphanumerics, lower-case), then compare the sequence with its reverse.",
         prereqs=["string_iteration"],
         wrong=["def is_palindrome(s):\n    return s == s[::-1]\n"]),
    mcq("py-p-m3", "problem_solving", "medium", "file_streaming",
        "A script must process a 4 GB log file line by line on a machine with 2 GB of RAM. Which approach works?",
        ["`data = f.read()` then `data.split('\\n')`",
         "`lines = f.readlines()` then loop over `lines`",
         "`for line in f:` and process each line as it is read",
         "`list(f)` first, so that the loop is faster"], 2,
        "File objects are lazy iterators: `for line in f` reads a buffer at a time and keeps memory flat. "
        "read(), readlines() and list(f) all load the entire file into memory.",
        type="scenario", prereqs=["generators_vs_lists"]),

    code("py-i-m1", "implementation", "medium", "text_processing",
         "Write `word_frequency(text)` that returns a dict mapping each word to the number of times it occurs. A word is a "
         "maximal run of letters A-Z (case-insensitive); words are lower-cased, and every other character (digits, "
         "punctuation, spaces) just separates words. For example `\"Hello, hello world!\"` gives `{\"hello\": 2, \"world\": 1}`.",
         "word_frequency", "def word_frequency(text):\n    pass\n",
         [T(["Hello, hello world!"], {"hello": 2, "world": 1}, True), T([""], {}, True),
          T(["It's 2 fun"], {"it": 1, "s": 1, "fun": 1}), T(["a A a"], {"a": 3}),
          T(["Don't stop-believing"], {"don": 1, "t": 1, "stop": 1, "believing": 1}),
          T(["the cat the hat the bat"], {"the": 3, "cat": 1, "hat": 1, "bat": 1})],
         "import re\n\ndef word_frequency(text):\n    counts = {}\n    for w in re.findall(r'[a-z]+', text.lower()):\n"
         "        counts[w] = counts.get(w, 0) + 1\n    return counts\n",
         "`re.findall('[a-z]+', text.lower())` extracts the words; a dict (or collections.Counter) tallies them.",
         prereqs=["string_split", "dict_methods"],
         wrong=["def word_frequency(text):\n    counts = {}\n    for w in text.split():\n        counts[w] = counts.get(w, 0) + 1\n    return counts\n"]),
    code("py-i-m2", "implementation", "medium", "recursion",
         "Write `flatten(nested)` that takes a list which may contain integers and further (arbitrarily deeply) nested lists, "
         "and returns a single flat list of the integers in their original left-to-right order. "
         "Example: `flatten([1, [2, [3, [4]]]])` is `[1, 2, 3, 4]`.",
         "flatten", "def flatten(nested):\n    pass\n",
         [T([[1, [2, [3, [4]]]]], [1, 2, 3, 4], True), T([[]], [], True), T([[[], [[]]]], []),
          T([[1, 2, 3]], [1, 2, 3]), T([[[1, 2], [3, [4, 5]], 6]], [1, 2, 3, 4, 5, 6]), T([_nested(200)], [1]),
          T([list(range(5000))], list(range(5000)))],
         "def flatten(nested):\n    out = []\n    for item in nested:\n        if isinstance(item, list):\n"
         "            out.extend(flatten(item))\n        else:\n            out.append(item)\n    return out\n",
         "Recurse into any element that is itself a list; append everything else. Order is preserved because you process items left to right.",
         prereqs=["loops_conditionals"],
         wrong=["def flatten(nested):\n    out = []\n    for item in nested:\n        if isinstance(item, list):\n            out.extend(item)\n"
                "        else:\n            out.append(item)\n    return out\n"]),
    code("py-i-m3", "implementation", "medium", "stack_design",
         "Implement a class `MinStack` with methods `push(x)`, `pop()` (removes and returns the top item), `top()` (returns the top item "
         "without removing it) and `get_min()` (returns the smallest item currently in the stack). All four must run in O(1) time. "
         "Calling `pop`, `top` or `get_min` on an empty stack must raise `IndexError`.",
         "MinStack",
         "class MinStack:\n    def __init__(self):\n        pass\n\n    def push(self, x):\n        pass\n\n    def pop(self):\n        pass\n\n"
         "    def top(self):\n        pass\n\n    def get_min(self):\n        pass\n",
         [{"ctor": [], "ops": [["push", 5], ["push", 3], ["get_min"], ["push", 7], ["top"], ["get_min"], ["pop"], ["pop"], ["get_min"]],
           "expected": [None, None, 3, None, 7, 3, 7, 3, 5], "visible": True},
          {"ctor": [], "ops": [["push", 2], ["push", 2], ["push", 1], ["get_min"], ["pop"], ["get_min"], ["pop"], ["get_min"]],
           "expected": [None, None, None, 1, 1, 2, 2, 2], "visible": True},
          {"ctor": [], "ops": [["pop"]], "raises": "IndexError"},
          {"ctor": [], "ops": [["get_min"]], "raises": "IndexError"},
          {"ctor": [], "ops": [["top"]], "raises": "IndexError"},
          {"ctor": [], "ops": [["push", i] for i in range(1000, 0, -1)] + [["get_min"]],
           "expected": [None] * 1000 + [1]}],
         "class MinStack:\n    def __init__(self):\n        self._s = []\n        self._m = []\n\n    def push(self, x):\n"
         "        self._s.append(x)\n        self._m.append(x if not self._m else min(x, self._m[-1]))\n\n    def pop(self):\n"
         "        if not self._s:\n            raise IndexError('pop from empty stack')\n        self._m.pop()\n        return self._s.pop()\n\n"
         "    def top(self):\n        if not self._s:\n            raise IndexError('empty stack')\n        return self._s[-1]\n\n"
         "    def get_min(self):\n        if not self._m:\n            raise IndexError('empty stack')\n        return self._m[-1]\n",
         "Keep a second stack holding the minimum-so-far at each depth; push/pop both stacks together so get_min() is just a peek.",
         prereqs=["mutability", "aliasing"],
         wrong=["class MinStack:\n    def __init__(self):\n        self._s = []\n    def push(self, x):\n        self._s.append(x)\n"
                "    def pop(self):\n        return self._s.pop()\n    def top(self):\n        return self._s[-1]\n"
                "    def get_min(self):\n        return min(self._s)\n"]),

    # =====================================================================
    # HARD (14)
    # =====================================================================
    mcq("py-f-h1", "fundamentals", "hard", "gil_concurrency",
        "You have a CPU-bound, pure-Python function and a 4-core machine. Which approach gives a genuine speed-up in standard CPython?",
        ["Run it in 4 `threading.Thread` objects",
         "Run it in 4 processes (`multiprocessing` / `ProcessPoolExecutor`)",
         "Wrap the work in 4 `asyncio` tasks",
         "Add `time.sleep(0)` calls so the interpreter schedules threads more fairly"], 1,
        "The Global Interpreter Lock lets only one thread execute Python bytecode at a time, so threads and asyncio do not parallelise "
        "CPU-bound work. Separate processes each have their own interpreter and GIL.",
        type="scenario", prereqs=[]),
    mcq("py-f-h2", "fundamentals", "hard", "decorators",
        "When writing a decorator, what does applying `functools.wraps(func)` to the inner wrapper function do?",
        ["It makes the wrapper run faster by caching results",
         "It copies metadata such as `__name__` and `__doc__` from `func` onto the wrapper",
         "It lets the decorator be applied to classes as well as functions",
         "It prevents the wrapped function from raising exceptions"], 1,
        "Without wraps, the decorated function reports the wrapper's name and docstring, which breaks introspection, help() and debugging output. "
        "`functools.wraps` copies `__name__`, `__doc__`, `__module__` and more.", prereqs=[]),

    output("py-c-h1", "hard", "closures_late_binding",
           "funcs = [lambda: i for i in range(3)]\nprint([f() for f in funcs])", "[2, 2, 2]",
           "Each lambda closes over the variable `i`, not its value at creation time. By the time the lambdas are called, `i` is 2 for all of them "
           "(late binding). Use `lambda i=i: i` to capture the value.", prereqs=["scope_basics"]),
    output("py-c-h2", "hard", "generators",
           "def counter():\n    n = 0\n    while True:\n        n += 1\n        yield n\n\ng = counter()\na = next(g)\nb = next(g)\n"
           "print(a, b, sum(next(g) for _ in range(3)))", "1 2 12",
           "The generator keeps its state between next() calls: a=1, b=2, then the next three values are 3, 4, 5 which sum to 12.",
           prereqs=["generators_vs_lists"]),
    output("py-c-h3", "hard", "shallow_vs_deep_copy",
           "import copy\n\na = [[1, 2], [3]]\nb = a.copy()\nc = copy.deepcopy(a)\na[0].append(99)\na.append([4])\nprint(b, c)",
           "[[1, 2, 99], [3]] [[1, 2], [3]]",
           "`a.copy()` is a shallow copy: b has its own outer list but shares the inner lists with a, so the 99 shows up in b "
           "while the later append of [4] to a does not. deepcopy duplicates the inner lists as well, so c is unaffected.",
           prereqs=["aliasing", "mutability"]),

    code("py-d-h1", "debugging", "hard", "sorting_precondition",
         "`merge_intervals(intervals)` should merge overlapping or touching intervals (inclusive) and return them sorted by start, e.g. "
         "`[[8, 10], [1, 3], [2, 6]]` becomes `[[1, 6], [8, 10]]`. It works for some inputs but not others. Fix it.",
         "merge_intervals",
         "def merge_intervals(intervals):\n    result = []\n    for start, end in intervals:\n"
         "        if result and start <= result[-1][1]:\n            result[-1][1] = max(result[-1][1], end)\n"
         "        else:\n            result.append([start, end])\n    return result\n",
         [T([[[8, 10], [1, 3], [2, 6]]], [[1, 6], [8, 10]], True), T([[[1, 4], [4, 5]]], [[1, 5]], True), T([[]], []),
          T([[[1, 10], [2, 3]]], [[1, 10]]), T([[[5, 6], [1, 2], [3, 4]]], [[1, 2], [3, 4], [5, 6]]),
          T([[[1, 3], [2, 6], [8, 10], [15, 18]]], [[1, 6], [8, 10], [15, 18]]),
          T([[[2, 3], [4, 5], [6, 7], [8, 9], [1, 10]]], [[1, 10]])],
         "def merge_intervals(intervals):\n    result = []\n    for start, end in sorted(intervals):\n"
         "        if result and start <= result[-1][1]:\n            result[-1][1] = max(result[-1][1], end)\n"
         "        else:\n            result.append([start, end])\n    return result\n",
         "The merge logic only works when intervals are processed in order of their start. The input is not guaranteed to be sorted, so sort first.",
         type="debug", prereqs=["sorted_vs_sort"],
         wrong=["def merge_intervals(intervals):\n    return [list(i) for i in intervals]\n"]),
    code("py-d-h2", "debugging", "hard", "mutable_default_args",
         "`add_tag(tag, tags=[])` should return a list containing `tag` appended to `tags` when a list is supplied; when no list is supplied it "
         "must start from a fresh empty list on EVERY call. Right now separate calls interfere with each other. Fix it.",
         "add_tag", "def add_tag(tag, tags=[]):\n    tags.append(tag)\n    return tags\n",
         [{"seq": [["a"], ["b"]], "expected": [["a"], ["b"]], "visible": True},
          {"seq": [["x", ["y"]], ["z"]], "expected": [["y", "x"], ["z"]], "visible": True},
          {"seq": [["p"], ["q"], ["r"]], "expected": [["p"], ["q"], ["r"]]},
          {"seq": [["a", []], ["b", []]], "expected": [["a"], ["b"]]},
          {"seq": [["k"], ["m", ["n"]], ["o"]], "expected": [["k"], ["n", "m"], ["o"]]}],
         "def add_tag(tag, tags=None):\n    if tags is None:\n        tags = []\n    tags.append(tag)\n    return tags\n",
         "Default values are evaluated once at definition time. Use `None` as the default and create the list inside the function.",
         type="debug", prereqs=["mutable_default_args", "aliasing"]),
    mcq("py-d-h3", "debugging", "hard", "scope_legb",
        "Calling `increment()` raises `UnboundLocalError: cannot access local variable 'count'`. What is the cause and the correct fix?",
        ["`count` is a module-level int, so it can never be changed; use a list instead",
         "Assigning to `count` inside the function makes it a local variable for the whole function; declare it with `global count` (or use a parameter/return value)",
         "Python requires `return` before any assignment inside a function",
         "The function must be defined before `count` is assigned"], 1,
        "If a function assigns to a name anywhere in its body, Python treats that name as local throughout. Reading it before assignment fails. "
        "Declare `global count` (or better, pass the value in and return the new value).",
        code="count = 0\n\ndef increment():\n    count += 1\n    return count\n\nincrement()", prereqs=["scope_basics"]),

    code("py-p-h1", "problem_solving", "hard", "sliding_window",
         "Write `longest_unique_substring(s)` that returns the LENGTH of the longest substring of `s` that contains no repeated character. "
         "Inputs can be tens of thousands of characters long, so an O(n^2) approach will time out.",
         "longest_unique_substring", "def longest_unique_substring(s):\n    pass\n",
         [T(["abcabcbb"], 3, True), T(["bbbbb"], 1, True), T(["pwwkew"], 3), T([""], 0), T(["dvdf"], 3), T(["abba"], 2),
          T(["ab" * 50000], 2), T([_CJK], 20000)],
         "def longest_unique_substring(s):\n    last = {}\n    best = start = 0\n    for i, ch in enumerate(s):\n"
         "        if ch in last and last[ch] >= start:\n            start = last[ch] + 1\n        last[ch] = i\n"
         "        best = max(best, i - start + 1)\n    return best\n",
         "Keep a window [start, i] and a dict of each character's last index. When a repeat falls inside the window, move `start` past it. One pass, O(n).",
         prereqs=["dict_methods", "string_iteration"],
         wrong=["def longest_unique_substring(s):\n    best = 0\n    for i in range(len(s)):\n        seen = set()\n"
                "        for ch in s[i:]:\n            if ch in seen:\n                break\n            seen.add(ch)\n"
                "        best = max(best, len(seen))\n    return best\n"]),
    code("py-p-h2", "problem_solving", "hard", "dynamic_programming",
         "Write `min_coins(coins, amount)` that returns the fewest coins (unlimited supply of each denomination) needed to make `amount`, "
         "or -1 if it is impossible. `min_coins(coins, 0)` is 0. Note that a greedy choice of the largest coin is not always optimal.",
         "min_coins", "def min_coins(coins, amount):\n    pass\n",
         [T([[1, 2, 5], 11], 3, True), T([[2], 3], -1, True), T([[1], 0], 0), T([[1, 3, 4], 6], 2),
          T([[186, 419, 83, 408], 6249], 20), T([[1, 2, 5], 100], 20), T([[1, 5, 10, 25], 9999], _min_coins([1, 5, 10, 25], 9999)),
          T([[7, 13], 50000], _min_coins([7, 13], 50000))],
         "def min_coins(coins, amount):\n    INF = float('inf')\n    dp = [0] + [INF] * amount\n    for a in range(1, amount + 1):\n"
         "        for c in coins:\n            if c <= a and dp[a - c] + 1 < dp[a]:\n                dp[a] = dp[a - c] + 1\n"
         "    return -1 if dp[amount] == INF else dp[amount]\n",
         "Bottom-up dynamic programming: dp[a] is the fewest coins for amount a, built from dp[a - coin] + 1. Greedy fails for e.g. coins [1, 3, 4] and amount 6.",
         prereqs=["recursion", "loops_conditionals"],
         wrong=["def min_coins(coins, amount):\n    n = 0\n    for c in sorted(coins, reverse=True):\n        n += amount // c\n"
                "        amount %= c\n    return n if amount == 0 else -1\n",
                "def min_coins(coins, amount):\n    if amount == 0:\n        return 0\n    best = -1\n    for c in coins:\n"
                "        if c <= amount:\n            r = min_coins(coins, amount - c)\n            if r != -1 and (best == -1 or r + 1 < best):\n"
                "                best = r + 1\n    return best\n"]),
    mcq("py-p-h3", "problem_solving", "hard", "complexity_analysis",
        "A function receives a list `data` with 100,000 items and builds its output with:\n\n    result = []\n    for x in data:\n        result = result + [x * 2]\n\n"
        "It becomes very slow as `data` grows. What is the cause?",
        ["Python for-loops are inherently slow, so nothing can be done",
         "`result + [x * 2]` creates a brand-new list and copies every existing element on each iteration, making the total work quadratic; `result.append(...)` is amortised O(1)",
         "Lists cannot hold more than a few thousand items efficiently",
         "The garbage collector runs on every loop iteration"], 1,
        "List concatenation with `+` allocates a new list and copies all previous elements each time: 1 + 2 + ... + n copies = O(n^2). "
        "`append` (or a list comprehension) is O(1) amortised per item, so the whole loop is O(n).",
        type="scenario", prereqs=["generators_vs_lists", "mutability"]),

    code("py-i-h1", "implementation", "hard", "heap_counter",
         "Write `top_k_frequent(words, k)` that returns the k most frequent words in a list, most frequent first. Words with equal frequency are "
         "ordered alphabetically. If there are fewer than k distinct words, return all of them. The input can contain hundreds of thousands of words.",
         "top_k_frequent", "def top_k_frequent(words, k):\n    pass\n",
         [T([["i", "love", "leetcode", "i", "love", "coding"], 2], ["i", "love"], True),
          T([["the", "day", "is", "sunny", "the", "the", "the", "sunny", "is", "is"], 4], ["the", "is", "sunny", "day"], True),
          T([[], 3], []), T([["a"], 5], ["a"]), T([["b", "a", "b", "a", "c"], 2], ["a", "b"]),
          T([_TOPK_WORDS, 3], _topk_expected(_TOPK_WORDS, 3))],
         "from collections import Counter\nimport heapq\n\ndef top_k_frequent(words, k):\n    counts = Counter(words)\n"
         "    return [w for w, _ in heapq.nsmallest(k, counts.items(), key=lambda kv: (-kv[1], kv[0]))]\n",
         "Count with a Counter, then pick the k best by the key (-count, word). `heapq.nsmallest` (or sorting the distinct words) handles ties alphabetically.",
         prereqs=["dict_counting", "sorted_vs_sort"],
         wrong=["from collections import Counter\n\ndef top_k_frequent(words, k):\n    return [w for w, _ in Counter(words).most_common(k)]\n"]),
    code("py-i-h2", "implementation", "hard", "class_design",
         "Implement `LRUCache(capacity)` with `get(key)` and `put(key, value)`. `get` returns the value, or -1 if the key is absent, and marks the key as "
         "most recently used. `put` inserts or updates a key and marks it most recently used; when the cache would exceed `capacity`, it evicts the "
         "least recently used key. Both operations must be O(1).",
         "LRUCache",
         "class LRUCache:\n    def __init__(self, capacity):\n        pass\n\n    def get(self, key):\n        pass\n\n    def put(self, key, value):\n        pass\n",
         [{"ctor": [2], "ops": [["put", 1, 1], ["put", 2, 2], ["get", 1], ["put", 3, 3], ["get", 2], ["put", 4, 4], ["get", 1], ["get", 3], ["get", 4]],
           "expected": [None, None, 1, None, -1, None, -1, 3, 4], "visible": True},
          {"ctor": [1], "ops": [["put", 1, 10], ["put", 2, 20], ["get", 1], ["get", 2]],
           "expected": [None, None, -1, 20], "visible": True},
          {"ctor": [2], "ops": [["put", 1, 1], ["put", 2, 2], ["put", 1, 100], ["put", 3, 3], ["get", 1], ["get", 2], ["get", 3]],
           "expected": [None, None, None, None, 100, -1, 3]},
          {"ctor": [3], "ops": [["put", 1, 1], ["put", 2, 2], ["put", 3, 3], ["get", 1], ["put", 4, 4], ["get", 2], ["get", 1], ["get", 3], ["get", 4]],
           "expected": [None, None, None, 1, None, -1, 1, 3, 4]},
          {"ctor": [100], "ops": [["put", i, i] for i in range(20000)] + [["get", 19999], ["get", 19899], ["get", 19900]],
           "expected": [None] * 20000 + [19999, -1, 19900]}],
         "from collections import OrderedDict\n\nclass LRUCache:\n    def __init__(self, capacity):\n        self.cap = capacity\n        self.d = OrderedDict()\n\n"
         "    def get(self, key):\n        if key not in self.d:\n            return -1\n        self.d.move_to_end(key)\n        return self.d[key]\n\n"
         "    def put(self, key, value):\n        self.d[key] = value\n        self.d.move_to_end(key)\n        if len(self.d) > self.cap:\n"
         "            self.d.popitem(last=False)\n",
         "An OrderedDict (or dict + doubly linked list) lets you move a key to the 'recent' end and evict from the 'old' end in O(1). "
         "Remember that a successful get() and an updating put() both count as a use.",
         prereqs=["stack_design", "dict_methods"],
         wrong=["class LRUCache:\n    def __init__(self, capacity):\n        self.cap = capacity\n        self.d = {}\n\n"
                "    def get(self, key):\n        return self.d.get(key, -1)\n\n"
                "    def put(self, key, value):\n        if key not in self.d and len(self.d) >= self.cap:\n"
                "            del self.d[next(iter(self.d))]\n        self.d[key] = value\n"]),
    code("py-i-h3", "implementation", "hard", "exceptions_parsing",
         "Write `parse_duration(text)` that converts a duration string made of one or more `<number><unit>` parts into total seconds. Units are `h` "
         "(3600), `m` (60) and `s` (1), each at most once, in that order; numbers are non-negative integers. Examples: `\"1h30m15s\"` -> 5415, `\"45s\"` -> 45, "
         "`\"2h\"` -> 7200. Raise `ValueError` for an empty string, unknown units, repeated or out-of-order units, a missing number or trailing characters "
         "(e.g. `\"\"`, `\"5\"`, `\"1x\"`, `\"30m1h\"`, `\"h\"`, `\"1h1h\"`).",
         "parse_duration", "def parse_duration(text):\n    pass\n",
         [T(["1h30m15s"], 5415, True), T(["45s"], 45, True), T(["2h"], 7200), T(["10m"], 600), T(["1h0m5s"], 3605),
          T(["0s"], 0), T(["100m"], 6000),
          T([""], None, raises="ValueError"), T(["5"], None, raises="ValueError"), T(["1x"], None, raises="ValueError"),
          T(["30m1h"], None, raises="ValueError"), T(["h"], None, raises="ValueError"), T(["1h1h"], None, raises="ValueError"),
          T(["1h30"], None, raises="ValueError")],
         "import re\n\n_UNITS = {'h': 3600, 'm': 60, 's': 1}\n\ndef parse_duration(text):\n"
         "    m = re.fullmatch(r'(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?', text)\n    if not text or m is None:\n        raise ValueError('bad duration: %r' % text)\n"
         "    h, mi, s = (int(g) if g else 0 for g in m.groups())\n    return h * 3600 + mi * 60 + s\n",
         "A single anchored regex (`re.fullmatch`) with three optional groups enforces the order, the uniqueness and the 'nothing left over' rules. "
         "The empty string matches the pattern, so it must be rejected explicitly.",
         prereqs=["text_processing", "string_normalization"],
         wrong=["def parse_duration(text):\n    total = 0\n    num = ''\n    for ch in text:\n        if ch.isdigit():\n            num += ch\n"
                "        else:\n            total += int(num) * {'h': 3600, 'm': 60, 's': 1}[ch]\n            num = ''\n    return total\n"]),
]

# ---------------------------------------------------------------------------
# Concept catalogue: what to tell the learner to study when they miss a concept.
# ---------------------------------------------------------------------------
CONCEPT_ADVICE = {
    "numeric_types": "int vs float behaviour, / vs //",
    "mutability": "mutable vs immutable types and why it matters",
    "dict_methods": "dictionary methods (get, setdefault, items) and counting patterns",
    "slicing": "sequence slicing and index arithmetic",
    "aliasing": "references vs copies of objects",
    "range_loops": "range() and for-loop mechanics",
    "assignment_vs_equality": "reading Python syntax errors",
    "scope_basics": "variable scope (local vs global)",
    "control_flow": "if/elif ordering and loop logic",
    "string_split": "str.split() and joining",
    "string_iteration": "iterating over and testing characters",
    "loops_conditionals": "loops with conditions and accumulators",
    "identity_vs_equality": "== vs is",
    "data_structure_choice": "choosing between list, set and dict",
    "generators_vs_lists": "generators, lazy evaluation and memory",
    "mutable_default_args": "mutable default arguments",
    "sorted_vs_sort": "sorted() vs list.sort() and sort keys",
    "dict_counting": "counting with dicts / collections.Counter",
    "logic_errors": "tracing conditions to find inverted logic",
    "off_by_one": "off-by-one errors in ranges and windows",
    "mutating_while_iterating": "modifying a list while iterating over it",
    "hash_lookup": "hash-map lookups to replace nested loops",
    "string_normalization": "cleaning and normalising text",
    "file_streaming": "streaming data instead of loading it all",
    "text_processing": "regular expressions and tokenising text",
    "recursion": "recursion and base cases",
    "stack_design": "designing small classes and auxiliary data structures",
    "gil_concurrency": "the GIL, threads vs processes vs asyncio",
    "decorators": "decorators and functools.wraps",
    "closures_late_binding": "closures and late binding",
    "generators": "generator functions and iterator state",
    "shallow_vs_deep_copy": "shallow vs deep copy",
    "sorting_precondition": "algorithm preconditions such as sorted input",
    "scope_legb": "the LEGB scope rule, global and nonlocal",
    "sliding_window": "sliding-window technique",
    "dynamic_programming": "dynamic programming vs greedy",
    "complexity_analysis": "Big-O reasoning about loops and copies",
    "heap_counter": "heapq, Counter and tie-breaking in sorts",
    "class_design": "designing classes with O(1) operations (OrderedDict, linked lists)",
    "exceptions_parsing": "parsing input and raising the right exceptions",
}
