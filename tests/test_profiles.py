import tempfile
import unittest
from pathlib import Path

from guardian_agent.cli import main
from guardian_agent.core import GuardianError, initialize
from guardian_agent.profiles import (
    CATALOG,
    PROHIBITED_MODELS,
    get_profile,
    list_profiles,
    prepare_profile_handoff,
    select_profiles,
    validate_catalog,
)


class AgentProfileCatalogTests(unittest.TestCase):
    def test_catalog_contains_all_planned_profiles_and_domains(self) -> None:
        result = validate_catalog()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["count"], 151)
        self.assertEqual(result["domain_count"], 10)
        self.assertEqual([profile.id for profile in CATALOG], list(range(1, 152)))

    def test_profiles_are_unique_complete_and_model_safe(self) -> None:
        self.assertEqual(len({profile.slug for profile in CATALOG}), 151)
        for profile in CATALOG:
            self.assertTrue(profile.input_contract)
            self.assertTrue(profile.output_contract)
            self.assertTrue(profile.verification)
            self.assertTrue(set(PROHIBITED_MODELS).issubset(profile.prohibited_models))

    def test_lookup_by_id_and_slug(self) -> None:
        self.assertEqual(get_profile(1)["name"], "Intent classifier")
        self.assertEqual(get_profile("frontend-developer")["id"], 47)
        with self.assertRaises(GuardianError):
            get_profile("not-a-real-profile")

    def test_domain_filter_is_compact(self) -> None:
        profiles = list_profiles("security-governance")
        self.assertEqual(len(profiles), 15)
        self.assertNotIn("input_contract", profiles[0])

    def test_selector_routes_representative_tasks(self) -> None:
        web = select_profiles("Build an accessible React frontend login form", limit=5)
        web_names = {item["name"] for item in web["selected"]}
        self.assertIn("Frontend developer", web_names)
        self.assertIn("Accessibility designer", web_names)

        debug = select_profiles("Find the root cause of a failing parser test", limit=3)
        self.assertEqual(debug["selected"][0]["name"], "Root-cause investigator")

    def test_selector_reports_large_context_savings(self) -> None:
        result = select_profiles("Review API security", limit=5)
        self.assertEqual(result["catalog_count"], 151)
        self.assertGreater(result["context"]["estimated_savings_percent"], 90)
        self.assertGreater(result["context"]["estimated_tokens_saved"], 0)


    def test_selector_diversifies_compound_tasks(self) -> None:
        result = select_profiles(
            "Build an accessible React login form with secure REST API, "
            "database migration, tests and deployment",
            limit=8,
        )
        names = {profile["name"] for profile in result["selected"]}
        self.assertIn("Frontend developer", names)
        self.assertIn("Accessibility designer", names)
        self.assertTrue(names & {"API architect", "API developer"})
        self.assertTrue(names & {"Migration architect", "Database developer"})
        self.assertIn("Unit-test writer", names)

    def test_selector_validates_input(self) -> None:
        with self.assertRaises(GuardianError):
            select_profiles("", limit=5)
        with self.assertRaises(GuardianError):
            select_profiles("task", limit=0)

    def test_profile_cli_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "demo"
            initialize(root, "Profiles", "CLI profile tests")
            self.assertEqual(main(["profile", "validate", "--project", str(root)]), 0)
            self.assertEqual(main([
                "profile", "select", "--project", str(root),
                "--task", "write unit tests", "--limit", "2",
            ]), 0)

    def test_dispatch_writes_bounded_handoff_and_journey(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "demo"
            brain = initialize(root, "Profiles", "Handoff tests")
            result = prepare_profile_handoff(
                brain, "Design and test a secure REST API", limit=4
            )
            handoff = Path(result["handoff_path"])
            self.assertTrue(handoff.is_file())
            content = handoff.read_text(encoding="utf-8")
            self.assertIn("Selected roles", content)
            self.assertIn("claude-sonnet-4.6", content)
            self.assertIn("Specialist Profiles Routed", brain.document("JOURNEY.md").read_text())


if __name__ == "__main__":
    unittest.main()
