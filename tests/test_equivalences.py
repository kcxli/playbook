from __future__ import annotations

import unittest
from pathlib import Path

from playbook_runner.equivalences import (
    OptionCandidate,
    best_match,
    equivalence_gap_report,
    state_abbreviation,
)


def utah_country_options() -> list[OptionCandidate]:
    fixture = Path(__file__).with_name("fixtures") / "utah_country_options.txt"
    return [
        OptionCandidate(line.strip())
        for line in fixture.read_text().splitlines()
        if line.strip()
    ]


class EquivalenceTests(unittest.TestCase):
    def test_state_abbreviation_returns_canonical_postal_code(self) -> None:
        self.assertEqual(state_abbreviation("Massachusetts"), "MA")
        self.assertEqual(state_abbreviation("British Columbia"), "BC")
        self.assertIsNone(state_abbreviation("Not Applicable (International)"))

    def test_state_abbreviation_to_name_with_state_context(self) -> None:
        match = best_match(
            "TX",
            [OptionCandidate("California"), OptionCandidate("Texas")],
            context="State/Province",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "Texas")

    def test_state_name_to_abbreviation_with_state_context(self) -> None:
        match = best_match(
            "Texas",
            [OptionCandidate("CA"), OptionCandidate("TX")],
            context="State",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "TX")

    def test_state_abbreviation_is_not_global(self) -> None:
        match = best_match(
            "IN",
            [OptionCandidate("In person"), OptionCandidate("Indiana")],
            context="Referral Source",
        )
        self.assertIsNone(match)

    def test_country_aliases(self) -> None:
        match = best_match(
            "US",
            [OptionCandidate("Canada"), OptionCandidate("United States of America")],
            context="Country",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "United States of America")

    def test_country_case_and_punctuation_do_not_matter(self) -> None:
        match = best_match(
            "u.s.a.",
            [OptionCandidate("United States")],
            context="Country of Residence",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "United States")

    def test_utah_country_code_prefix_labels(self) -> None:
        options = [
            OptionCandidate("USA - United States of America"),
            OptionCandidate("CAN - Canada"),
            OptionCandidate("UMI - United States Minor Outlying Islands"),
            OptionCandidate("KOR - Korea, Republic of"),
        ]

        us_match = best_match("United States", options, context="Country")
        self.assertIsNotNone(us_match)
        self.assertEqual(us_match.candidate.label, "USA - United States of America")

        canada_match = best_match("Canada", options, context="Country")
        self.assertIsNotNone(canada_match)
        self.assertEqual(canada_match.candidate.label, "CAN - Canada")

        korea_match = best_match("South Korea", options, context="Country")
        self.assertIsNotNone(korea_match)
        self.assertEqual(korea_match.candidate.label, "KOR - Korea, Republic of")

    def test_utah_country_code_prefix_uses_country_name_not_only_code(self) -> None:
        options = [
            OptionCandidate("AUT - Australia"),
            OptionCandidate("AUT - Austria"),
        ]

        australia_match = best_match("Australia", options, context="Country")
        self.assertIsNotNone(australia_match)
        self.assertEqual(australia_match.candidate.label, "AUT - Australia")

        austria_match = best_match("Austria", options, context="Country")
        self.assertIsNotNone(austria_match)
        self.assertEqual(austria_match.candidate.label, "AUT - Austria")

    def test_all_utah_country_code_prefix_labels_match_their_country_name(self) -> None:
        options = utah_country_options()

        for option in options:
            with self.subTest(option=option.label):
                wanted = option.label.split(" - ", 1)[1]
                match = best_match(wanted, options, context="Country")
                self.assertIsNotNone(match)
                self.assertEqual(match.candidate.label, option.label)

    def test_utah_country_common_profile_aliases(self) -> None:
        options = utah_country_options()
        cases = {
            "Bahamas": "BHS - Bahama",
            "Czechia": "CZE - Czech Republic",
            "Iran": "IRN - Islamic Republic of Iran",
            "North Korea": "PRK - Korea, Democratic People's Republic of",
            "Laos": "LAO - Lao People's Democratic Republic",
            "Libya": "LBY - Libyan Arab Jamahiriya",
            "Palestine": "PSE - Palestinian Territory, Occupied",
            "Democratic Republic of the Congo": "COD - Congo, Democratic Republic of the",
            "North Macedonia": "MKD - North Macedonia, Republic of",
            "UK": "GBR - United Kingdom (Great Britain)",
            "US Virgin Islands": "VIR - United States Virgin Islands",
            "Vatican City": "VAT - Vatican City State (Holy See)",
            "Vietnam": "VNM - Viet Nam",
        }

        for wanted, expected in cases.items():
            with self.subTest(wanted=wanted):
                match = best_match(wanted, options, context="Country")
                self.assertIsNotNone(match)
                self.assertEqual(match.candidate.label, expected)

    def test_utah_state_dropdown_labels(self) -> None:
        options = [
            OptionCandidate("Not Applicable (Int'l Candidate)"),
            OptionCandidate("MA"),
            OptionCandidate("UT"),
        ]

        state_match = best_match("Massachusetts", options, context="State")
        self.assertIsNotNone(state_match)
        self.assertEqual(state_match.candidate.label, "MA")

        intl_match = best_match("N/A", options, context="State")
        self.assertIsNotNone(intl_match)
        self.assertEqual(intl_match.candidate.label, "Not Applicable (Int'l Candidate)")

    def test_utah_state_dropdown_territory_military_and_canadian_codes(self) -> None:
        options = [
            OptionCandidate(label)
            for label in [
                "Not Applicable (Int'l Candidate)",
                "AS", "GU", "MH", "MP", "PR", "VI",
                "AE", "AA", "AP",
                "AB", "BC", "NF", "ON", "QC", "YT",
            ]
        ]

        cases = {
            "American Samoa": "AS",
            "Guam": "GU",
            "Puerto Rico": "PR",
            "US Virgin Islands": "VI",
            "Armed Forces Europe": "AE",
            "Military Americas": "AA",
            "British Columbia": "BC",
            "Newfoundland and Labrador": "NF",
            "Quebec": "QC",
        }
        for wanted, expected in cases.items():
            with self.subTest(wanted=wanted):
                match = best_match(wanted, options, context="State")
                self.assertIsNotNone(match)
                self.assertEqual(match.candidate.label, expected)

    def test_utah_highest_degree_code_prefix_labels(self) -> None:
        options = [
            OptionCandidate("A-Not Indicated"),
            OptionCandidate("B-Less Than HS Graduate"),
            OptionCandidate("C-HS Graduate or Equivalent"),
            OptionCandidate("D-Some College"),
            OptionCandidate("E-Technical School"),
            OptionCandidate("F-2-Year College Degree"),
            OptionCandidate("G-Bachelor's Level Degree"),
            OptionCandidate("H-Some Graduate School"),
            OptionCandidate("I-Master's Level Degree"),
            OptionCandidate("J-Doctorate (Academic)"),
            OptionCandidate("K-Doctorate (Professional)"),
            OptionCandidate("L-Post-Doctorate"),
        ]

        doctorate_match = best_match("Doctorate", options, context="Highest Degree")
        self.assertIsNotNone(doctorate_match)
        self.assertEqual(doctorate_match.candidate.label, "J-Doctorate (Academic)")

        masters_match = best_match("Masters", options, context="Highest Degree")
        self.assertIsNotNone(masters_match)
        self.assertEqual(masters_match.candidate.label, "I-Master's Level Degree")

        bachelors_match = best_match("Bachelors", options, context="Highest Degree")
        self.assertIsNotNone(bachelors_match)
        self.assertEqual(bachelors_match.candidate.label, "G-Bachelor's Level Degree")

        high_school_match = best_match("High School", options, context="Highest Degree")
        self.assertIsNotNone(high_school_match)
        self.assertEqual(high_school_match.candidate.label, "C-HS Graduate or Equivalent")

        professional_match = best_match("Professional Degree", options, context="Highest Degree")
        self.assertIsNotNone(professional_match)
        self.assertEqual(professional_match.candidate.label, "K-Doctorate (Professional)")

        postdoc_match = best_match("Post-Doctorate", options, context="Highest Degree")
        self.assertIsNotNone(postdoc_match)
        self.assertEqual(postdoc_match.candidate.label, "L-Post-Doctorate")

    def test_gender_abbreviation_with_gender_context(self) -> None:
        match = best_match(
            "M",
            [OptionCandidate("Female"), OptionCandidate("Male")],
            context="Gender",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "Male")

    def test_gender_abbreviation_is_not_global(self) -> None:
        match = best_match(
            "M",
            [OptionCandidate("Married"), OptionCandidate("Male")],
            context="Marital Status",
        )
        self.assertIsNone(match)

    def test_pronoun_aliases_with_pronoun_context(self) -> None:
        match = best_match(
            "she/her",
            [OptionCandidate("He/Him/His"), OptionCandidate("She/Her/Hers")],
            context="Pronouns",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "She/Her/Hers")

    def test_utah_disability_status_labels(self) -> None:
        options = [
            OptionCandidate("Yes, I Have A Disability, Or Have A History/Record Of Having A Disability "),
            OptionCandidate("No, I Don\u2019t Have A Disability, Or A History/Record Of Having A Disability"),
            OptionCandidate("I Don\u2019t Wish To Answer"),
        ]

        yes_match = best_match("yes", options, context="Disability Status")
        self.assertIsNotNone(yes_match)
        self.assertEqual(
            yes_match.candidate.label,
            "Yes, I Have A Disability, Or Have A History/Record Of Having A Disability ",
        )

        no_match = best_match("No, I Don't Have A Disability", options, context="Disability Status")
        self.assertIsNotNone(no_match)
        self.assertEqual(
            no_match.candidate.label,
            "No, I Don\u2019t Have A Disability, Or A History/Record Of Having A Disability",
        )

        decline_match = best_match("decline", options, context="Disability Status")
        self.assertIsNotNone(decline_match)
        self.assertEqual(decline_match.candidate.label, "I Don\u2019t Wish To Answer")

    def test_utah_citizenship_status_labels(self) -> None:
        options = [
            OptionCandidate("1-Citizen"),
            OptionCandidate("5-Permanent Resident"),
            OptionCandidate("4-Alien Authorized to Work"),
            OptionCandidate("8-Noncitizen National of the United States"),
        ]

        citizen_match = best_match("US Citizen", options, context="Citizenship Status")
        self.assertIsNotNone(citizen_match)
        self.assertEqual(citizen_match.candidate.label, "1-Citizen")

        resident_match = best_match("Green Card Holder", options, context="Citizenship Status")
        self.assertIsNotNone(resident_match)
        self.assertEqual(resident_match.candidate.label, "5-Permanent Resident")

        opt_match = best_match("F-1 OPT", options, context="Citizenship Status")
        self.assertIsNotNone(opt_match)
        self.assertEqual(opt_match.candidate.label, "4-Alien Authorized to Work")

        national_match = best_match("Noncitizen National", options, context="Citizenship Status")
        self.assertIsNotNone(national_match)
        self.assertEqual(national_match.candidate.label, "8-Noncitizen National of the United States")

    def test_citizen_does_not_match_noncitizen_national(self) -> None:
        match = best_match(
            "Citizen",
            [OptionCandidate("8-Noncitizen National of the United States")],
            context="Citizenship Status",
        )
        self.assertIsNone(match)

    def test_decline_wording(self) -> None:
        match = best_match(
            "I decline",
            [
                OptionCandidate("Yes"),
                OptionCandidate("No"),
                OptionCandidate("I do not wish to provide this information"),
            ],
            context="Veteran Status",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "I do not wish to provide this information")

    def test_nonbinary_does_not_silently_become_decline(self) -> None:
        match = best_match(
            "Non-Binary",
            [
                OptionCandidate("Female"),
                OptionCandidate("Male"),
                OptionCandidate("I do not wish to provide this information"),
            ],
            context="Gender",
        )
        self.assertIsNone(match)

    def test_degree_aliases(self) -> None:
        match = best_match(
            "Ph.D.",
            [OptionCandidate("Bachelor's Degree"), OptionCandidate("Doctorate")],
            context="Highest Degree",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "Doctorate")

    def test_verbose_degree_alias(self) -> None:
        match = best_match(
            "Ph.D. - Doctor of Philosophy",
            [OptionCandidate("Doctorate (Academic)")],
            context="Degree",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "Doctorate (Academic)")

    def test_phone_type_aliases(self) -> None:
        match = best_match(
            "Cellular Phone",
            [OptionCandidate("Home"), OptionCandidate("Mobile")],
            context="Primary Number",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "Mobile")

    def test_yes_no_prefix(self) -> None:
        match = best_match(
            "No",
            [
                OptionCandidate("Yes, I have a disability, or have had one in the past"),
                OptionCandidate("No, I do not have a disability and have not had one in the past"),
            ],
            context="Disability Status",
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            match.candidate.label,
            "No, I do not have a disability and have not had one in the past",
        )

    def test_sponsorship_negative_without_no_prefix(self) -> None:
        match = best_match(
            False,
            [
                OptionCandidate("I will require visa sponsorship"),
                OptionCandidate("I do not require visa sponsorship"),
            ],
            context="Will you now or in the future require sponsorship?",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "I do not require visa sponsorship")

    def test_work_authorization_positive_without_yes_prefix(self) -> None:
        match = best_match(
            True,
            [
                OptionCandidate("I am not authorized to work in the United States"),
                OptionCandidate("I am currently authorized to work in the United States"),
            ],
            context="Are you authorized to work in the United States?",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "I am currently authorized to work in the United States")

    def test_referral_aliases(self) -> None:
        match = best_match(
            "HERC",
            [OptionCandidate("Higher Education Recruitment Consortium")],
            context="How did you hear about this position?",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "Higher Education Recruitment Consortium")

    def test_canadian_province_aliases(self) -> None:
        match = best_match(
            "BC",
            [OptionCandidate("British Columbia")],
            context="State/Province",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "British Columbia")

    def test_salary_range_contains_amount(self) -> None:
        match = best_match(
            "82000",
            [
                OptionCandidate("$60,000 - $79,999"),
                OptionCandidate("$80,000 - $99,999"),
                OptionCandidate("$100,000+"),
            ],
            context="Desired Salary",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "$80,000 - $99,999")

    def test_salary_range_k_notation(self) -> None:
        match = best_match(
            "$82k",
            [
                OptionCandidate("60k - 79k"),
                OptionCandidate("80k - 99k"),
                OptionCandidate("100k+"),
            ],
            context="Compensation",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "80k - 99k")

    def test_salary_open_ended_above(self) -> None:
        match = best_match(
            "125000",
            [
                OptionCandidate("$80,000 - $99,999"),
                OptionCandidate("At least $100,000"),
            ],
            context="Salary expectation",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "At least $100,000")

    def test_salary_open_ended_under(self) -> None:
        match = best_match(
            "45000",
            [
                OptionCandidate("Under $50,000"),
                OptionCandidate("$50,000 - $69,999"),
            ],
            context="Desired pay",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "Under $50,000")

    def test_salary_nearest_range_only_when_close(self) -> None:
        match = best_match(
            "100000",
            [
                OptionCandidate("$80,000 - $99,999"),
                OptionCandidate("$120,000 - $139,999"),
            ],
            context="Desired Salary",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.candidate.label, "$80,000 - $99,999")

    def test_salary_far_range_does_not_guess(self) -> None:
        match = best_match(
            "82000",
            [
                OptionCandidate("Under $40,000"),
                OptionCandidate("$150,000+"),
            ],
            context="Desired Salary",
        )
        self.assertIsNone(match)

    def test_salary_range_is_context_aware(self) -> None:
        match = best_match(
            "82000",
            [OptionCandidate("$80,000 - $99,999")],
            context="Graduation Year",
        )
        self.assertIsNone(match)

    def test_equivalence_gap_report_includes_repair_context(self) -> None:
        report = equivalence_gap_report(
            "Job Board",
            [
                OptionCandidate("Employee Referral", value="employee", index=0),
                OptionCandidate("Web-based Job Posting Board", value="web", index=1),
            ],
            context="Referral Source",
            action="select",
        )

        self.assertEqual(report["kind"], "equivalence_gap")
        self.assertEqual(report["wanted_normalized"], "job board")
        self.assertIn("referral", report["active_groups"])
        self.assertEqual(report["candidates"][1]["index"], 1)
        self.assertEqual(report["candidates"][1]["candidate_index"], 1)
        self.assertEqual(
            report["candidates"][1]["label_normalized"],
            "web based job posting board",
        )


if __name__ == "__main__":
    unittest.main()
