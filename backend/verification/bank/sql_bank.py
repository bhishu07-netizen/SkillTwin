"""
SQL question bank (37 questions: 13 easy / 12 medium / 12 hard) - no code execution by the candidate.

Types: mcq / scenario (single answer, options shuffled per attempt) and output (type the result rows).
`output` answers are NOT typed in by an author: they are produced at import time by executing the query
against the sample database below with Python's sqlite3, so the key can never disagree with real SQL.
"Pick the query" questions carry `_verify` (target query); tests/test_sql_bank.py executes every option and
proves the keyed option returns exactly the target result and every distractor differs or errors.
Extra keys (`_verify`) are never sent to a client.
"""
import sqlite3

SKILL = "sql"

SETUP = """
CREATE TABLE emp(id INTEGER PRIMARY KEY, name TEXT, dept TEXT, salary INTEGER, manager_id INTEGER);
INSERT INTO emp VALUES (1,'Asha','Eng',90,NULL),(2,'Ben','Eng',70,1),(3,'Chen','Ops',60,1),
  (4,'Dia','Ops',60,3),(5,'Eli','HR',50,1),(6,'Fay','Eng',NULL,2);
CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, city TEXT);
INSERT INTO customers VALUES (1,'Ana','Pune'),(2,'Raj','Delhi'),(3,'Meg','Pune'),(4,'Sam','Goa');
CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER, amount INTEGER);
INSERT INTO orders VALUES (1,1,100),(2,1,50),(3,2,200),(4,3,75),(5,3,25),(6,5,60);
"""


def connect():
    db = sqlite3.connect(":memory:")
    db.executescript(SETUP)
    return db


def fmt(rows):
    return "\n".join("|".join("NULL" if v is None else str(v) for v in r) for r in rows)


def run(query):
    """Execute against the sample DB -> canonical text. Raises on SQL errors."""
    db = connect()
    try:
        return fmt(db.execute(query).fetchall())
    finally:
        db.close()


def view(*tables):
    db = connect()
    out = []
    for t in tables:
        cols = [r[1] for r in db.execute("PRAGMA table_info(%s)" % t)]
        out.append("%s(%s)" % (t, ", ".join(cols)))
        for r in db.execute("SELECT * FROM %s" % t):
            out.append("  " + ", ".join("NULL" if v is None else str(v) for v in r))
    db.close()
    return "\n".join(out)


def mcq(id, category, difficulty, concept, prompt, options, answer, explanation, *, code=None, prereqs=(),
        type="mcq", time_hint_s=60, verify=None):
    q = {"id": id, "skill": SKILL, "category": category, "difficulty": difficulty, "concept": concept,
         "prereqs": list(prereqs), "type": type, "prompt": prompt, "code": code, "options": options,
         "answer": answer, "explanation": explanation, "time_hint_s": time_hint_s}
    if verify:
        q["_verify"] = verify
    return q


def pick(id, category, difficulty, concept, prompt, target, correct, wrong, explanation, *, tables, prereqs=(),
         type="scenario"):
    """'Which query does X?' - the correct query is placed at a position derived from the id (options are
    additionally shuffled per attempt). `target` is what the correct query must return on the sample data."""
    pos = sum(map(ord, id)) % (len(wrong) + 1)
    options = list(wrong)
    options.insert(pos, correct)
    return mcq(id, category, difficulty, concept, prompt, options, pos, explanation, code=view(*tables),
               prereqs=prereqs, type=type, time_hint_s=90, verify={"target": target})


def output(id, difficulty, concept, query, explanation, *, tables, prereqs=()):
    return {"id": id, "skill": SKILL, "category": "code_reading", "difficulty": difficulty, "concept": concept,
            "prereqs": list(prereqs), "type": "output",
            "prompt": "What does this query return on the tables below? Type the result rows exactly: one row per "
                      "line, columns separated by |, NULL for NULL (no header).",
            "code": view(*tables) + "\n\n" + query, "expected": run(query), "explanation": explanation,
            "time_hint_s": 90}


FUND, CR, DBG, PS, IMP = "fundamentals", "code_reading", "debugging", "problem_solving", "implementation"

QUESTIONS = [
    # ------------------------------------------------------------------ fundamentals
    mcq("sql-f-e1", FUND, "easy", "where_vs_having", "Which clause filters individual rows before any grouping happens?",
        ["WHERE", "HAVING", "GROUP BY", "ORDER BY"], 0,
        "WHERE filters rows before grouping; HAVING filters groups after aggregation."),
    mcq("sql-f-e2", FUND, "easy", "count_star", "Column x is NULL in 3 of the 10 rows of table t. Which expression returns 10?",
        ["COUNT(x)", "COUNT(*)", "COUNT(DISTINCT x)", "SUM(x)"], 1,
        "COUNT(*) counts rows. COUNT(x) skips NULLs (7) and DISTINCT reduces it further."),
    mcq("sql-f-e3", FUND, "easy", "distinct", "Which keyword removes duplicate rows from a query result?",
        ["UNIQUE", "ONLY", "DISTINCT", "DIFFERENT"], 2, "SELECT DISTINCT removes duplicate result rows."),
    mcq("sql-f-e4", FUND, "easy", "primary_key", "Which statement best describes a PRIMARY KEY?",
        ["It uniquely identifies each row of the table", "It always sorts the table on disk by that column",
         "It permits duplicate values if the other columns differ", "It links a row to a row in another table"], 0,
        "A primary key identifies each row uniquely. Linking to another table is the job of a FOREIGN KEY."),
    mcq("sql-f-m1", FUND, "medium", "outer_joins",
        "Which join returns every row from the left table even when there is no matching row on the right?",
        ["INNER JOIN", "LEFT JOIN", "CROSS JOIN", "NATURAL JOIN"], 1,
        "LEFT JOIN keeps unmatched left rows and fills the right columns with NULL.", prereqs=["where_vs_having"]),
    mcq("sql-f-m2", FUND, "medium", "union_vs_union_all", "What is the difference between UNION and UNION ALL?",
        ["UNION ALL removes duplicate rows, UNION keeps them", "UNION removes duplicate rows, UNION ALL keeps them",
         "UNION works on one table only", "There is no difference"], 1,
        "UNION de-duplicates (extra sorting/hashing work); UNION ALL simply concatenates."),
    mcq("sql-f-m3", FUND, "medium", "null_aggregates", "The salary column holds 70, 60 and NULL. What does AVG(salary) return?",
        ["65", "43.33", "NULL", "130"], 0,
        "Aggregates other than COUNT(*) ignore NULLs: (70 + 60) / 2 = 65.", prereqs=["count_star"]),
    mcq("sql-f-h1", FUND, "hard", "not_in_null",
        "orders.customer_id contains at least one NULL. What does "
        "`SELECT name FROM customers WHERE id NOT IN (SELECT customer_id FROM orders)` return?",
        ["Customers without orders", "No rows at all", "Every customer", "A runtime error"], 1,
        "x NOT IN (..., NULL) evaluates to UNKNOWN for every x, so no row passes. Use NOT EXISTS or filter the NULLs.",
        prereqs=["null_aggregates"]),
    mcq("sql-f-h2", FUND, "hard", "window_ranking",
        "Salaries are 90, 80, 80, 70. What does RANK() OVER (ORDER BY salary DESC) return for the 70?",
        ["2", "3", "4", "1"], 2,
        "RANK gives tied rows the same rank and leaves a gap: 1, 2, 2, 4. DENSE_RANK would give 3.",
        prereqs=["union_vs_union_all"]),
    mcq("sql-f-h3", FUND, "hard", "index_prefix", "A composite index exists on (a, b). Which filter can NOT use it to seek efficiently?",
        ["WHERE a = 5", "WHERE a = 5 AND b = 7", "WHERE b = 7", "WHERE a = 5 ORDER BY b"], 2,
        "B-tree indexes are usable from the leftmost column: a, or a then b. A filter on b alone cannot seek.",
        prereqs=["primary_key"]),

    # ------------------------------------------------------------------ code reading (answers computed by SQLite)
    output("sql-c-e1", "easy", "filtering", "SELECT name FROM emp WHERE dept = 'Ops' ORDER BY name;",
           "Only the two Ops employees match; ORDER BY sorts them alphabetically.", tables=["emp"]),
    output("sql-c-e2", "easy", "null_comparison", "SELECT COUNT(*) FROM emp WHERE salary > 60;",
           "Only 90 and 70 exceed 60. Fay's salary is NULL, and NULL > 60 is UNKNOWN, so she is excluded.",
           tables=["emp"], prereqs=["filtering"]),
    output("sql-c-e3", "easy", "group_by_count", "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY dept;",
           "GROUP BY makes one row per department; COUNT(*) counts the rows in each.", tables=["emp"]),
    output("sql-c-m1", "medium", "left_join_count",
           "SELECT c.name, COUNT(o.id) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id\nGROUP BY c.id ORDER BY c.id;",
           "LEFT JOIN keeps Sam; COUNT(o.id) counts only non-NULL order ids, so Sam gets 0. The order for customer 5 "
           "has no customer row and never appears.", tables=["customers", "orders"], prereqs=["outer_joins"]),
    output("sql-c-m2", "medium", "avg_group", "SELECT dept, AVG(salary) FROM emp GROUP BY dept ORDER BY dept;",
           "AVG ignores NULL: Eng is (90 + 70) / 2 = 80.0, not 160 / 3.", tables=["emp"], prereqs=["null_aggregates"]),
    output("sql-c-m3", "medium", "boolean_logic",
           "SELECT name FROM emp WHERE salary > 55 AND (dept = 'Ops' OR dept = 'HR') ORDER BY name;",
           "Eli (50) fails the salary test; the two Ops employees pass both.", tables=["emp"], prereqs=["filtering"]),
    output("sql-c-h1", "hard", "window_partition",
           "SELECT name, RANK() OVER (PARTITION BY dept ORDER BY salary DESC)\nFROM emp WHERE salary IS NOT NULL ORDER BY name;",
           "Ranking restarts in every department; the tied Ops salaries both rank 1.", tables=["emp"],
           prereqs=["window_ranking"]),
    output("sql-c-h2", "hard", "self_join",
           "SELECT e.name, m.name FROM emp e JOIN emp m ON e.manager_id = m.id ORDER BY e.id;",
           "A self-join pairs each employee with their manager; Asha has no manager so the inner join drops her.",
           tables=["emp"], prereqs=["outer_joins"]),
    output("sql-c-h3", "hard", "coalesce_aggregates",
           "SELECT COALESCE(SUM(salary), 0), COUNT(salary), COUNT(*) FROM emp WHERE dept = 'Eng';",
           "SUM and COUNT(salary) skip Fay's NULL salary (160 and 2) while COUNT(*) counts all three Eng rows.",
           tables=["emp"], prereqs=["null_aggregates"]),

    # ------------------------------------------------------------------ debugging
    mcq("sql-d-e1", DBG, "easy", "group_by_rules",
        "`SELECT dept, name, COUNT(*) FROM emp GROUP BY dept;` is rejected by standard SQL engines. Why?",
        ["`name` is neither grouped nor aggregated", "COUNT(*) cannot be combined with GROUP BY",
         "`dept` cannot be selected", "GROUP BY requires an ORDER BY"], 0,
        "Every selected column must be in GROUP BY or inside an aggregate - a department has many names."),
    mcq("sql-d-e2", DBG, "easy", "aggregate_in_where",
        "`SELECT name FROM emp WHERE salary > AVG(salary);` fails. What is the correct explanation?",
        ["Aggregates cannot be used in WHERE; compare against a subquery instead", "AVG always needs a GROUP BY",
         "`salary` is a reserved word", "`>` cannot compare numbers"], 0,
        "WHERE runs before aggregation. Use `WHERE salary > (SELECT AVG(salary) FROM emp)`.",
        prereqs=["where_vs_having"]),
    mcq("sql-d-m1", DBG, "medium", "left_join_where",
        "`SELECT c.name, o.amount FROM customers c LEFT JOIN orders o ON o.customer_id = c.id WHERE o.amount > 50` was "
        "meant to keep every customer, yet customers without orders vanish. Why?",
        ["The WHERE condition on the right table discards the NULL-extended rows, turning it into an inner join",
         "LEFT JOIN cannot be combined with WHERE", "o.amount must be quoted", "Customers need an index on id"], 0,
        "Put the condition in the ON clause (or test `o.amount IS NULL OR ...`) to keep unmatched customers.",
        prereqs=["outer_joins"]),
    mcq("sql-d-m2", DBG, "medium", "count_after_left_join",
        "A report built with LEFT JOIN shows customers who have no orders with an order count of 1. What is the fix?",
        ["Use COUNT(o.id) instead of COUNT(*)", "Use COUNT(DISTINCT c.id)", "Switch to INNER JOIN",
         "Add ORDER BY c.id"], 0,
        "COUNT(*) counts the NULL-extended row itself. COUNT(o.id) ignores NULLs, giving 0.",
        prereqs=["count_star", "outer_joins"]),
    mcq("sql-d-h1", DBG, "hard", "join_fanout",
        "A query joins orders to order_items and then does SUM(orders.amount) per customer; the totals are far too "
        "large. What is happening and what is the fix?",
        ["Each order row is repeated once per item, so its amount is summed repeatedly - aggregate before joining",
         "SUM overflows on large tables - use BIGINT", "The join must be a LEFT JOIN", "The GROUP BY needs HAVING"], 0,
        "A one-to-many join multiplies the 'one' side. Aggregate each side in a subquery first, then join.",
        prereqs=["left_join_where"]),
    mcq("sql-d-h2", DBG, "hard", "sargable_predicates",
        "`WHERE LOWER(email) = 'a@b.com'` scans the whole table even though `email` is indexed. Why?",
        ["Wrapping the column in a function prevents the plain index being used - use an expression index or store a "
         "normalised copy", "LOWER() is not allowed in WHERE", "Indexes only work on numeric columns",
         "The index must be rebuilt after every query"], 0,
        "A predicate must be 'sargable' (column compared directly) for the index on that column to be used.",
        prereqs=["index_prefix"]),

    # ------------------------------------------------------------------ problem solving (scenario; verified by execution)
    pick("sql-p-e1", PS, "easy", "order_limit", "You need the two highest-paid employees' names. Which query does that?",
         "SELECT name FROM emp ORDER BY salary DESC LIMIT 2",
         "SELECT name FROM emp ORDER BY salary DESC LIMIT 2",
         ["SELECT name FROM emp ORDER BY salary LIMIT 2", "SELECT MAX(salary) FROM emp", "SELECT name FROM emp ORDER BY salary DESC"],
         "ORDER BY ... DESC puts the largest first and LIMIT keeps two. Ascending order would return the lowest "
         "(and NULLs sort first in SQLite).", tables=["emp"]),
    pick("sql-p-e2", PS, "easy", "group_by_count", "You need how many orders each customer id has placed. Which query?",
         "SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id ORDER BY customer_id",
         "SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id ORDER BY customer_id",
         ["SELECT COUNT(*) FROM orders", "SELECT customer_id FROM orders ORDER BY customer_id",
          "SELECT customer_id, COUNT(*) FROM orders"],
         "GROUP BY customer_id creates one group per customer; COUNT(*) counts each group's rows.", tables=["orders"]),
    pick("sql-p-m1", PS, "medium", "anti_join", "Find the customers who have never placed an order. Which query is correct?",
         "SELECT c.name FROM customers c LEFT JOIN orders o ON o.customer_id = c.id WHERE o.id IS NULL",
         "SELECT c.name FROM customers c LEFT JOIN orders o ON o.customer_id = c.id WHERE o.id IS NULL",
         ["SELECT c.name FROM customers c INNER JOIN orders o ON o.customer_id = c.id WHERE o.id IS NULL",
          "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders)",
          "SELECT name FROM customers WHERE id = NULL"],
         "A LEFT JOIN anti-join keeps customers with no match (o.id IS NULL). An INNER JOIN can never produce NULLs, and "
         "`= NULL` is never true.", tables=["customers", "orders"], prereqs=["outer_joins"]),
    pick("sql-p-m2", PS, "medium", "nth_highest", "Which query returns the second-highest salary as a single value?",
         "SELECT MAX(salary) FROM emp WHERE salary < (SELECT MAX(salary) FROM emp)",
         "SELECT MAX(salary) FROM emp WHERE salary < (SELECT MAX(salary) FROM emp)",
         ["SELECT salary FROM emp ORDER BY salary DESC LIMIT 2", "SELECT MIN(salary) FROM emp",
          "SELECT MAX(salary) - 1 FROM emp"],
         "The inner query finds the maximum; the outer takes the largest value below it. LIMIT 2 returns two rows.",
         tables=["emp"], prereqs=["order_limit"]),
    pick("sql-p-h1", PS, "hard", "greatest_per_group",
         "Return the name(s) of the highest-paid employee in each department (ties included), ordered by name.",
         "SELECT e.name FROM emp e JOIN (SELECT dept, MAX(salary) AS m FROM emp GROUP BY dept) x "
         "ON x.dept = e.dept AND x.m = e.salary ORDER BY e.name",
         "SELECT e.name FROM emp e JOIN (SELECT dept, MAX(salary) AS m FROM emp GROUP BY dept) x "
         "ON x.dept = e.dept AND x.m = e.salary ORDER BY e.name",
         ["SELECT name FROM emp WHERE salary = (SELECT MAX(salary) FROM emp)", "SELECT dept, MAX(salary) FROM emp GROUP BY dept",
          "SELECT name FROM emp ORDER BY salary DESC LIMIT 1"],
         "Compute the per-department maximum in a subquery, then join back to find who earns it. The other queries "
         "return one global winner or no names.", tables=["emp"], prereqs=["nth_highest", "window_partition"]),
    mcq("sql-p-h2", PS, "hard", "query_tuning",
        "An orders table has 50 million rows. `WHERE created_at >= '2026-01-01' ORDER BY created_at DESC LIMIT 20` "
        "takes 12 seconds. What is the best first step?",
        ["Check the query plan and add an index on created_at", "Fetch everything and filter in application code",
         "Remove the LIMIT clause", "Convert the table into a view"], 0,
        "Look at the plan, then give the planner an index it can seek and read in order. The other options add work.",
        type="scenario", prereqs=["index_prefix", "sargable_predicates"]),

    # ------------------------------------------------------------------ implementation (pick the right query; verified)
    pick("sql-i-e1", IMP, "easy", "filtering", "Which query returns the names of everyone in the Eng department, ordered by id?",
         "SELECT name FROM emp WHERE dept = 'Eng' ORDER BY id",
         "SELECT name FROM emp WHERE dept = 'Eng' ORDER BY id",
         ["SELECT name FROM emp WHERE dept = 'Ops' ORDER BY id", "SELECT name FROM emp WHERE dept <> 'Eng' ORDER BY id",
          "SELECT name WHERE dept = 'Eng' FROM emp"],
         "String literals use single quotes and the clause order is SELECT, FROM, WHERE, ORDER BY.",
         tables=["emp"], type="mcq"),
    pick("sql-i-e2", IMP, "easy", "sum_basics", "Which query returns the total value of all orders?",
         "SELECT SUM(amount) FROM orders", "SELECT SUM(amount) FROM orders",
         ["SELECT COUNT(amount) FROM orders", "SELECT MAX(amount) FROM orders", "SELECT amount FROM orders"],
         "SUM adds the values; COUNT counts them and MAX picks one.", tables=["orders"], type="mcq"),
    pick("sql-i-m1", IMP, "medium", "having_clause", "Which query lists the departments whose average salary is above 65?",
         "SELECT dept FROM emp GROUP BY dept HAVING AVG(salary) > 65 ORDER BY dept",
         "SELECT dept FROM emp GROUP BY dept HAVING AVG(salary) > 65 ORDER BY dept",
         ["SELECT dept FROM emp WHERE AVG(salary) > 65 GROUP BY dept",
          "SELECT dept FROM emp GROUP BY dept HAVING SUM(salary) > 65 ORDER BY dept",
          "SELECT DISTINCT dept FROM emp ORDER BY dept"],
         "Conditions on aggregates belong in HAVING. SUM is not AVG, and WHERE cannot hold aggregates.",
         tables=["emp"], type="mcq", prereqs=["where_vs_having"]),
    pick("sql-i-m2", IMP, "medium", "left_join_aggregate",
         "Which query lists every customer with their total spend, showing 0 for customers with no orders (ordered by id)?",
         "SELECT c.name, COALESCE(SUM(o.amount), 0) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id "
         "GROUP BY c.id ORDER BY c.id",
         "SELECT c.name, COALESCE(SUM(o.amount), 0) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id "
         "GROUP BY c.id ORDER BY c.id",
         ["SELECT c.name, SUM(o.amount) FROM customers c INNER JOIN orders o ON o.customer_id = c.id GROUP BY c.id ORDER BY c.id",
          "SELECT c.name, SUM(o.amount) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id GROUP BY c.id ORDER BY c.id",
          "SELECT name, amount FROM customers, orders"],
         "LEFT JOIN keeps customers without orders; SUM over no rows is NULL, and COALESCE turns it into 0.",
         tables=["customers", "orders"], type="mcq", prereqs=["left_join_count", "null_aggregates"]),
    pick("sql-i-h1", IMP, "hard", "running_total", "Which query returns each order id with the running total of amount in id order?",
         "SELECT id, SUM(amount) OVER (ORDER BY id) FROM orders ORDER BY id",
         "SELECT id, SUM(amount) OVER (ORDER BY id) FROM orders ORDER BY id",
         ["SELECT id, SUM(amount) FROM orders GROUP BY id ORDER BY id", "SELECT id, SUM(amount) OVER () FROM orders ORDER BY id",
          "SELECT id, amount + LAG(amount) OVER (ORDER BY id) FROM orders ORDER BY id"],
         "A windowed SUM with ORDER BY accumulates row by row. Without ORDER BY the window is the whole table.",
         tables=["orders"], type="mcq", prereqs=["window_ranking"]),
    pick("sql-i-h2", IMP, "hard", "correlated_subquery",
         "Which query returns, for each customer id, the amount of their most recent order (highest order id), ordered by customer id?",
         "SELECT o.customer_id, o.amount FROM orders o WHERE o.id = (SELECT MAX(id) FROM orders WHERE customer_id = o.customer_id) "
         "ORDER BY o.customer_id",
         "SELECT o.customer_id, o.amount FROM orders o WHERE o.id = (SELECT MAX(id) FROM orders WHERE customer_id = o.customer_id) "
         "ORDER BY o.customer_id",
         ["SELECT customer_id, MAX(amount) FROM orders GROUP BY customer_id ORDER BY customer_id",
          "SELECT customer_id, amount FROM orders ORDER BY id DESC LIMIT 1",
          "SELECT customer_id, MIN(id) FROM orders GROUP BY customer_id ORDER BY customer_id"],
         "A correlated subquery finds each customer's latest order id; the outer query reads that order's amount.",
         tables=["orders"], type="mcq", prereqs=["running_total"]),
]

CONCEPT_ADVICE = {
    "where_vs_having": "WHERE (rows) vs HAVING (groups) and the logical order of SQL clauses",
    "count_star": "COUNT(*) vs COUNT(column) vs COUNT(DISTINCT column)",
    "distinct": "removing duplicates with DISTINCT",
    "primary_key": "keys and constraints (PRIMARY KEY, FOREIGN KEY, UNIQUE)",
    "outer_joins": "INNER vs LEFT joins and NULL-extended rows",
    "union_vs_union_all": "set operations: UNION vs UNION ALL",
    "null_aggregates": "how NULL behaves in aggregates and comparisons",
    "not_in_null": "three-valued logic: NOT IN with NULLs, prefer NOT EXISTS",
    "window_ranking": "window functions: RANK, DENSE_RANK, ROW_NUMBER",
    "index_prefix": "how B-tree and composite indexes are used (leftmost prefix)",
    "filtering": "WHERE filters, quoting literals, ORDER BY",
    "null_comparison": "comparisons with NULL are UNKNOWN (use IS NULL)",
    "group_by_count": "GROUP BY with COUNT",
    "left_join_count": "counting across LEFT JOINs",
    "avg_group": "AVG per group and NULL handling",
    "boolean_logic": "AND/OR precedence and parentheses",
    "window_partition": "PARTITION BY in window functions",
    "self_join": "joining a table to itself (hierarchies)",
    "coalesce_aggregates": "COALESCE and NULL-safe aggregation",
    "group_by_rules": "what may appear in the SELECT list of a grouped query",
    "aggregate_in_where": "why aggregates cannot appear in WHERE",
    "left_join_where": "filters on the right table of a LEFT JOIN (ON vs WHERE)",
    "count_after_left_join": "counting after an outer join",
    "join_fanout": "one-to-many join fan-out inflating aggregates",
    "sargable_predicates": "writing index-friendly (sargable) predicates",
    "order_limit": "ORDER BY with LIMIT for top-N",
    "anti_join": "finding rows with no match (anti-join, NOT EXISTS)",
    "nth_highest": "nth-highest value patterns",
    "greatest_per_group": "greatest-per-group queries",
    "query_tuning": "reading query plans and indexing for performance",
    "sum_basics": "basic aggregate functions",
    "having_clause": "filtering aggregated groups with HAVING",
    "left_join_aggregate": "aggregating over LEFT JOINs with COALESCE",
    "running_total": "cumulative sums with window frames",
    "correlated_subquery": "correlated subqueries",
}
