"""Standards alignment for every lesson: NGSS, CSTA K-12 CS Standards (2017 codes, the set most states adopted)
and the National AFNR Career Cluster Content Standards (2015), Power, Structural & Technical Systems pathway,
with Plant Systems and Environmental Service Systems where a lesson fits them better.

"Primary" = the lesson's activities and assessment address the standard; "supports" = it builds toward it.
Self-assessed by AgriSense Hub: districts should check it against their own state standards.
"""

NGSS = {
    "HS-ESS2-5": "Plan and conduct an investigation of the properties of water and its effects on Earth materials and surface processes.",
    "HS-ESS3-4": "Evaluate or refine a technological solution that reduces impacts of human activities on natural systems.",
    "HS-ETS1-2": "Design a solution to a complex real-world problem by breaking it down into smaller, more manageable problems that can be solved through engineering.",
    "HS-ETS1-3": "Evaluate a solution to a complex real-world problem based on prioritized criteria and trade-offs.",
    "MS-ESS3-3": "Apply scientific principles to design a method for monitoring and minimizing a human impact on the environment.",
    "MS-LS1-5": "Construct a scientific explanation based on evidence for how environmental and genetic factors influence the growth of organisms.",
    "MS-ETS1-4": "Develop a model to generate data for iterative testing and modification of a proposed object, tool, or process.",
}
SEP = {1: "Asking questions and defining problems", 2: "Developing and using models", 3: "Planning and carrying out investigations",
       4: "Analyzing and interpreting data", 5: "Using mathematics and computational thinking",
       6: "Constructing explanations and designing solutions", 7: "Engaging in argument from evidence",
       8: "Obtaining, evaluating, and communicating information"}
CCC = {1: "Patterns", 2: "Cause and effect", 3: "Scale, proportion, and quantity", 4: "Systems and system models",
       5: "Energy and matter", 6: "Structure and function", 7: "Stability and change"}

CSTA = {
    "2-CS-02": "Design projects that combine hardware and software components to collect and exchange data.",
    "2-CS-03": "Systematically identify and fix problems with computing devices and their components.",
    "2-DA-08": "Collect data using computational tools and transform the data to make it more useful and reliable.",
    "2-AP-12": "Design and iteratively develop programs that combine control structures, including nested loops and compound conditionals.",
    "2-AP-17": "Systematically test and refine programs using a range of test cases.",
    "3A-CS-03": "Develop guidelines that convey systematic troubleshooting strategies that others can use to identify and fix errors.",
    "3A-DA-11": "Create interactive data visualizations using software tools to help others better understand real-world phenomena.",
    "3A-DA-12": "Create computational models that represent the relationships among different elements of data collected from a phenomenon or process.",
    "3A-AP-13": "Create prototypes that use algorithms to solve computational problems by leveraging prior student knowledge and personal interests.",
    "3A-AP-16": "Design and iteratively develop computational artifacts for practical intent, personal expression, or to address a societal issue by using events to initiate instructions.",
    "3A-IC-24": "Evaluate the ways computing impacts personal, ethical, social, economic, and cultural practices.",
    "3B-CS-02": "Illustrate ways computing systems implement logic, input, and output through hardware components.",
    "3B-DA-05": "Use data analysis tools and techniques to identify patterns in data representing complex systems.",
    "3B-DA-06": "Select data collection tools and techniques to generate data sets that support a claim or communicate information.",
    "3B-DA-07": "Evaluate the ability of models and simulations to test and support the refinement of hypotheses.",
    "3B-AP-08": "Describe how artificial intelligence drives many software and physical systems.",
    "3B-IC-25": "Evaluate computational artifacts to maximize their beneficial effects and minimize harmful effects on society.",
}

AFNR = {
    "PST.03.04": "Troubleshoot and service electrical systems.",
    "PST.05.01": "Use instruments and meters to test and monitor electrical and electronic processes.",
    "PST.05.02": "Prepare and/or use electrical drawings to design, install and troubleshoot …",
    "PST.05.03": "Use geospatial technologies in agricultural applications.",
    "PS.02.01": "Determine the influence of environmental factors on plant growth.",
    "PS.02.02": "Prepare growing media for use in plant systems (soil water, drainage, water-holding capacity, irrigation).",
    "PS.02.03": "Develop and implement a fertilization plan for specific plants or crops (nutrients, pH).",
    "PS.03.02": "Develop and implement a plant management plan for crop production.",
    "ESS.03.03": "Apply hydrology principles to environmental service systems.",
}
AI4K12 = {1: "Perception", 2: "Representation and reasoning", 3: "Learning", 4: "Natural interaction", 5: "Societal impact"}
AFNR_PATHWAYS = {"PST": "Power, Structural & Technical Systems", "PS": "Plant Systems", "ESS": "Environmental Service Systems"}

# lesson -> dict(ngss=[(code, "primary"|"supports")], sep=[..], ccc=[..], csta=[..], afnr=[..])
MAP = {
    "1.1": dict(ngss=[("MS-LS1-5", "supports"), ("HS-ESS2-5", "supports")], sep=[1, 3], ccc=[6, 2],
                csta=["2-DA-08"], afnr=["PS.02.02", "PS.02.01"]),
    "1.2": dict(ngss=[("HS-ESS2-5", "supports")], sep=[3, 4], ccc=[3],
                csta=["2-DA-08", "3B-CS-02"], afnr=["PST.05.01", "PS.02.03"]),
    "1.3": dict(ngss=[("HS-ESS2-5", "primary")], sep=[3, 4, 5], ccc=[2, 7],
                csta=["3A-DA-11", "3B-DA-05"], afnr=["PS.02.02"]),
    "1.4": dict(ngss=[("MS-ESS3-3", "supports"), ("HS-ESS2-5", "supports")], sep=[3, 5], ccc=[3, 2],
                csta=["3A-DA-12"], afnr=["PS.02.02", "ESS.03.03"]),
    "1.5": dict(ngss=[("MS-LS1-5", "primary")], sep=[4, 6], ccc=[2],
                csta=["3B-DA-06"], afnr=["PS.02.03", "PS.02.01"]),
    "1.6": dict(ngss=[("HS-ETS1-2", "primary")], sep=[2, 6], ccc=[4, 5],
                csta=["2-CS-02", "3B-CS-02", "2-CS-03"], afnr=["PST.05.02", "PST.05.01", "PST.03.04"]),
    "1.7": dict(ngss=[("MS-ETS1-4", "supports")], sep=[4, 8], ccc=[4],
                csta=["3A-DA-11", "2-CS-02", "3A-AP-16"], afnr=["PST.05.01"]),
    "1.8": dict(ngss=[("HS-ETS1-3", "primary"), ("HS-ESS3-4", "primary"), ("MS-ESS3-3", "primary")], sep=[2, 5, 6], ccc=[4, 7],
                csta=["2-AP-12", "2-AP-17", "3A-AP-13", "3A-AP-16"], afnr=["PST.05.02", "ESS.03.03"]),
    "1.9": dict(ngss=[("HS-ESS3-4", "primary"), ("HS-ETS1-3", "supports")], sep=[4, 7, 8], ccc=[1],
                csta=["3B-DA-05", "3B-DA-06", "3A-DA-11"], afnr=["PS.03.02", "PS.02.02"]),
    "2.1": dict(ai4k12=[3], ngss=[("HS-ESS2-5", "supports")], sep=[4, 5], ccc=[2, 7],
                csta=["3A-DA-12", "3B-DA-07", "3B-AP-08"], afnr=["PS.02.02"]),
    "2.2": dict(ai4k12=[1, 3], ngss=[("MS-LS1-5", "supports")], sep=[3, 4], ccc=[1],
                csta=["3B-AP-08", "3B-DA-06", "3A-IC-24"], afnr=["PS.02.01"]),
    "2.3": dict(ai4k12=[3], ngss=[("HS-ETS1-3", "supports")], sep=[4], ccc=[4],
                csta=["3A-CS-03", "3B-DA-05", "3B-AP-08"], afnr=["PST.05.01", "PST.03.04"]),
    "2.4": dict(ai4k12=[2], ngss=[("HS-ESS3-4", "supports")], sep=[4, 5], ccc=[1],
                csta=["3B-DA-05", "3B-AP-08"], afnr=["PST.05.03", "PS.03.02"]),
    "2.5": dict(ai4k12=[5], ngss=[("HS-ETS1-3", "primary")], sep=[7], ccc=[2],
                csta=["3A-IC-24", "3B-IC-25", "3B-AP-08"], afnr=[]),
}


def short_codes(code):
    """One line for lesson lists: 'HS-ESS2-5 · SEP 3, 4 · CSTA 3A-DA-11 · AFNR PS.02.02'."""
    m = MAP.get(code)
    if not m:
        return ""
    bits = [", ".join(c for c, _ in m["ngss"])]
    if m["sep"]:
        bits.append("SEP " + ", ".join(str(s) for s in m["sep"]))
    if m["csta"]:
        bits.append("CSTA " + ", ".join(m["csta"]))
    if m["afnr"]:
        bits.append("AFNR " + ", ".join(m["afnr"]))
    if m.get("ai4k12"):
        bits.append("AI4K12 Big Idea " + ", ".join(str(i) for i in m["ai4k12"]))
    return " · ".join(b for b in bits if b)


def coverage():
    """Which lessons address each code, for the matrix on the standards page."""
    out = {"ngss": {}, "csta": {}, "afnr": {}}
    for lesson, m in MAP.items():
        for c, level in m["ngss"]:
            out["ngss"].setdefault(c, []).append((lesson, level))
        for c in m["csta"]:
            out["csta"].setdefault(c, []).append((lesson, "primary"))
        for c in m["afnr"]:
            out["afnr"].setdefault(c, []).append((lesson, "primary"))
    return out
