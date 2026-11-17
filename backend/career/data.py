"""
Career dataset: skill dependency graph + target-role requirement graphs.

ILLUSTRATIVE SAMPLE DATA - not live O*NET/ESCO/job-postings data. Every number the engine
shows traces back to this file, and the UI says so. Replacing this module with a real
ingestion pipeline is the intended production path; the engine only depends on the shapes here.

  SKILLS[skill]  demand (0-100 market-demand index), hours (illustrative hours to climb ONE level),
                 prereqs (AND-dependencies, a DAG), category, aliases (text extraction), project.
  ROLES[role]    aliases, summary, reqs = [(skill, importance 0-100, required_level, freq%)]
                 freq% = share of this role's sample postings that mention the skill (evidence).
"""

LEVEL_ORDER = ["Beginner", "Intermediate", "Advanced"]

# skill: (category, demand, hours_per_level, prereqs, aliases, project)
_S = {
    "python": ("programming", 92, 40, [], ["python", "python programming", "python3", "python development", "python scripting"],
               "Build a small data-processing script solving a real problem you care about."),
    "git": ("engineering", 80, 12, [], ["git", "version control", "github"],
            "Put an existing project under clean version control with a commit history."),
    "linux": ("engineering", 70, 25, [], ["linux", "unix", "bash scripting", "shell scripting"],
              "Set up a small Linux VM and automate a task with shell scripts."),
    "networking": ("security", 66, 30, [], ["networking", "computer networks", "tcp/ip", "tcp ip"],
                   "Capture and analyse traffic for a simple request with Wireshark."),
    "algorithms": ("programming", 78, 60, ["python"], ["algorithms", "data structures", "dsa"],
                   "Solve and write up 30 graded problems covering arrays, hashing, trees and graphs."),
    "sql": ("data", 90, 30, [], ["sql", "mysql", "postgresql", "structured query language"],
            "Build an analytics dashboard by querying a public dataset with SQL."),
    "excel": ("data", 76, 20, [], ["excel", "ms excel", "spreadsheets"],
              "Build a working analysis model in Excel using formulas and pivot tables."),
    "numpy": ("data", 70, 15, ["python"], ["numpy"], "Re-implement a few statistics routines with vectorised NumPy."),
    "pandas": ("data", 82, 25, ["python", "numpy"], ["pandas"],
               "Clean and analyze a messy dataset end-to-end using pandas."),
    "statistics": ("mathematics", 80, 40, [], ["statistics", "stats", "statistical analysis"],
                   "Analyze a public dataset and write up statistically-supported conclusions."),
    "linear algebra": ("mathematics", 66, 40, [], ["linear algebra", "matrices", "matrix algebra"],
                       "Implement PCA from scratch using eigen-decomposition."),
    "data visualization": ("data", 72, 20, ["excel"], ["data visualization", "dataviz", "visualization", "tableau charts"],
                           "Create a data-story dashboard visualizing a dataset you know well."),
    "power bi": ("data", 62, 20, ["data visualization"], ["power bi", "powerbi"],
                 "Build an interactive Power BI report from a public dataset."),
    "tableau": ("data", 55, 20, ["data visualization"], ["tableau"],
                "Build an interactive Tableau dashboard from a public dataset."),
    "machine learning": ("ml", 90, 60, ["python", "statistics", "linear algebra"],
                         ["machine learning", "ml", "machine-learning"],
                         "Train and evaluate a classification model on a public dataset."),
    "feature engineering": ("ml", 68, 25, ["pandas", "statistics"], ["feature engineering"],
                            "Improve a baseline model by engineering and validating new features."),
    "regression": ("ml", 74, 25, ["machine learning"], ["regression", "linear regression", "logistic regression"],
                   "Predict house prices with regularised regression and explain the coefficients."),
    "classification": ("ml", 76, 25, ["machine learning"], ["classification", "classifiers"],
                       "Build a spam/not-spam classifier and compare three algorithms."),
    "model evaluation": ("ml", 82, 20, ["regression", "classification"],
                         ["model evaluation", "cross validation", "cross-validation", "precision recall"],
                         "Write an evaluation report: cross-validation, confusion matrix, error analysis."),
    "scikit-learn": ("ml", 72, 20, ["python", "numpy"], ["scikit-learn", "sklearn", "scikit learn"],
                     "Build an ML pipeline (preprocessing + model + evaluation) with scikit-learn."),
    "deep learning": ("ml", 70, 50, ["machine learning", "linear algebra", "numpy"],
                      ["deep learning", "neural networks", "dl", "pytorch", "tensorflow"],
                      "Build an image classifier using a small neural network."),
    "rest apis": ("engineering", 78, 20, [], ["rest api", "restful", "api development", "flask api", "fastapi"],
                  "Build and document a small REST API with authentication and tests."),
    "docker": ("engineering", 78, 20, ["linux"], ["docker", "containerization"],
               "Containerize an existing project and document how to run it."),
    "aws": ("engineering", 80, 40, ["linux", "networking"], ["aws", "amazon web services", "cloud"],
            "Deploy a small app/API to a cloud service and document the setup."),
    "ci/cd": ("engineering", 70, 20, ["git", "docker"], ["ci/cd", "github actions", "continuous integration", "jenkins"],
              "Add a pipeline that tests, builds and deploys a project on every push."),
    "model deployment": ("ml", 76, 30, ["model evaluation", "rest apis", "docker"],
                         ["model deployment", "mlops", "model serving"],
                         "Serve a trained model behind a containerised API with a health check."),
    "testing": ("engineering", 72, 20, ["python"], ["unit testing", "pytest", "test driven", "tdd", "software testing"],
                "Add a unit-test suite with >80% coverage to an existing project."),
    "system design": ("engineering", 68, 50, ["algorithms", "sql", "rest apis"], ["system design", "software architecture"],
                      "Design (on paper) a URL shortener: data model, API, scaling and failure modes."),
    "java": ("programming", 70, 50, [], ["java"], "Build a small backend service in Java with a REST endpoint."),
    "javascript": ("programming", 76, 40, [], ["javascript", "js", "node.js", "node"],
                   "Build a small interactive web app or API client in JavaScript."),
    "communication": ("business", 74, 20, [], ["communication", "stakeholder communication", "presentation skills"],
                      "Present a project's findings to a non-technical audience."),
    "security fundamentals": ("security", 82, 40, ["networking"],
                              ["security fundamentals", "cybersecurity", "cyber security", "information security", "infosec"],
                              "Threat-model a small web app and write up the top 10 risks with mitigations."),
    "cryptography": ("security", 62, 35, ["security fundamentals"], ["cryptography", "encryption"],
                     "Implement and break a classical cipher, then use a modern AEAD library correctly."),
    "network security": ("security", 78, 35, ["networking", "security fundamentals"],
                         ["network security", "firewalls", "intrusion detection"],
                         "Harden a lab network: firewall rules, segmentation and IDS alerts."),
    "vulnerability assessment": ("security", 70, 30, ["network security", "linux"],
                                 ["vulnerability assessment", "penetration testing", "pentesting", "nmap"],
                                 "Scan an intentionally vulnerable VM and write a prioritised findings report."),
    "incident response": ("security", 72, 30, ["security fundamentals", "linux", "networking"],
                          ["incident response", "siem", "soc analyst"],
                          "Investigate a log dataset, build an incident timeline and a containment plan."),
    "r": ("data", 45, 30, [], ["r programming", "r language", "rstudio"], "Reproduce a Python analysis in R."),
}

SKILLS = {k: {"category": v[0], "demand": v[1], "hours": v[2], "prereqs": list(v[3]), "aliases": list(v[4]),
              "project": v[5]} for k, v in _S.items()}

# role: (aliases, summary, [(skill, importance, required_level, freq%)])
_R = {
    "ML Engineer": (["machine learning engineer", "mle", "ml eng", "mlops engineer"],
                    "Builds, evaluates and ships machine-learning models to production.",
                    [("python", 95, "Advanced", 90), ("machine learning", 95, "Advanced", 85), ("sql", 78, "Intermediate", 52),
                     ("statistics", 75, "Intermediate", 62), ("linear algebra", 70, "Intermediate", 45),
                     ("numpy", 60, "Intermediate", 58), ("pandas", 72, "Intermediate", 65),
                     ("feature engineering", 60, "Intermediate", 40), ("regression", 68, "Intermediate", 44),
                     ("classification", 74, "Intermediate", 52), ("model evaluation", 85, "Intermediate", 60),
                     ("scikit-learn", 66, "Intermediate", 55), ("deep learning", 78, "Intermediate", 60),
                     ("model deployment", 88, "Intermediate", 58), ("rest apis", 66, "Intermediate", 45),
                     ("docker", 72, "Intermediate", 50), ("aws", 62, "Beginner", 45), ("git", 58, "Intermediate", 55)]),
    "Data Scientist": (["data science", "ds", "data scientist"],
                       "Extracts insight and predictive models from data.",
                       [("python", 95, "Advanced", 88), ("statistics", 92, "Advanced", 80), ("machine learning", 88, "Intermediate", 78),
                        ("sql", 82, "Intermediate", 70), ("pandas", 82, "Intermediate", 66), ("numpy", 55, "Intermediate", 48),
                        ("linear algebra", 55, "Beginner", 40), ("feature engineering", 70, "Intermediate", 50),
                        ("regression", 76, "Intermediate", 55), ("classification", 70, "Intermediate", 50),
                        ("model evaluation", 80, "Intermediate", 55), ("scikit-learn", 68, "Intermediate", 50),
                        ("deep learning", 45, "Beginner", 30), ("data visualization", 68, "Intermediate", 52),
                        ("communication", 62, "Intermediate", 40)]),
    "Data Analyst": (["analyst", "bi analyst", "business intelligence analyst", "data analytics"],
                     "Turns data into reports and decisions with SQL, spreadsheets and BI tools.",
                     [("sql", 95, "Advanced", 82), ("excel", 85, "Intermediate", 75), ("statistics", 72, "Intermediate", 68),
                      ("data visualization", 82, "Intermediate", 65), ("power bi", 68, "Intermediate", 45),
                      ("tableau", 35, "Beginner", 25), ("python", 58, "Intermediate", 55), ("pandas", 50, "Intermediate", 40),
                      ("communication", 72, "Intermediate", 40)]),
    "Software Engineer": (["swe", "software developer", "programmer", "sde"],
                          "Designs, builds and maintains software systems.",
                          [("algorithms", 90, "Advanced", 70), ("python", 62, "Intermediate", 45), ("java", 60, "Intermediate", 40),
                           ("javascript", 58, "Intermediate", 42), ("git", 88, "Intermediate", 80), ("testing", 76, "Intermediate", 55),
                           ("rest apis", 82, "Intermediate", 62), ("sql", 72, "Intermediate", 65),
                           ("system design", 72, "Intermediate", 45), ("docker", 56, "Intermediate", 48),
                           ("ci/cd", 56, "Intermediate", 45), ("linux", 56, "Intermediate", 50), ("aws", 48, "Beginner", 40),
                           ("communication", 52, "Intermediate", 40)]),
    "Cybersecurity Analyst": (["security analyst", "soc analyst", "infosec analyst", "cyber security analyst", "cybersecurity"],
                              "Detects, investigates and prevents security threats.",
                              [("security fundamentals", 95, "Advanced", 85), ("networking", 90, "Intermediate", 80),
                               ("linux", 82, "Intermediate", 70), ("network security", 88, "Intermediate", 72),
                               ("vulnerability assessment", 78, "Intermediate", 55), ("incident response", 82, "Intermediate", 58),
                               ("cryptography", 62, "Intermediate", 40), ("python", 56, "Intermediate", 50),
                               ("communication", 56, "Intermediate", 45), ("aws", 46, "Beginner", 35)]),
    "Backend Developer": (["backend engineer", "back end developer", "server side developer"],
                          "Builds the server-side services behind applications.",
                          [("java", 80, "Intermediate", 60), ("sql", 80, "Intermediate", 65), ("git", 80, "Intermediate", 70),
                           ("rest apis", 78, "Intermediate", 60), ("docker", 60, "Intermediate", 45), ("aws", 55, "Beginner", 40),
                           ("javascript", 50, "Intermediate", 42), ("algorithms", 62, "Intermediate", 40),
                           ("testing", 60, "Intermediate", 45), ("linux", 45, "Intermediate", 40)]),
    "Business Analyst": (["ba", "business analysis", "product analyst"],
                         "Bridges business needs and data-driven solutions.",
                         [("excel", 90, "Intermediate", 80), ("communication", 92, "Advanced", 85), ("sql", 62, "Intermediate", 55),
                          ("statistics", 55, "Intermediate", 45), ("data visualization", 60, "Intermediate", 50),
                          ("power bi", 56, "Intermediate", 42)]),
}

ROLES = {name: {"aliases": v[0], "summary": v[1],
                "reqs": {s: {"importance": i, "required": lvl, "freq": f} for s, i, lvl, f in v[2]}}
         for name, v in _R.items()}

DATASET_NOTE = ("Illustrative sample dataset (%d roles, %d skills): importance, market-demand index, posting frequency, "
                "dependencies and effort hours are demo assumptions - not live O*NET/ESCO/job-posting data." %
                (len(ROLES), len(SKILLS)))


def validate():
    """Referential integrity + the dependency graph must be a DAG. Runs at import."""
    for s, d in SKILLS.items():
        for p in d["prereqs"]:
            assert p in SKILLS, "%s has unknown prerequisite %s" % (s, p)
    for r, d in ROLES.items():
        for s, q in d["reqs"].items():
            assert s in SKILLS, "%s requires unknown skill %s" % (r, s)
            assert q["required"] in LEVEL_ORDER and 0 < q["importance"] <= 100
    state = {}

    def visit(n, path):
        if state.get(n) == 1:
            raise AssertionError("dependency cycle: " + " -> ".join(path + [n]))
        if state.get(n) == 2:
            return
        state[n] = 1
        for p in SKILLS[n]["prereqs"]:
            visit(p, path + [n])
        state[n] = 2

    for n in SKILLS:
        visit(n, [])


validate()
