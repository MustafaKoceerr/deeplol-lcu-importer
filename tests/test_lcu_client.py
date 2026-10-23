from deeplol_importer.lcu_client import (
    LCUClient,
    resolve_summoner_spells,
)
from deeplol_importer.models import ItemBlockData, NormalizedBuild, RunePageData


class FakeLCUTransport:
    def __init__(self, pages: list[dict], item_sets_payload: dict) -> None:
        self.pages = list(pages)
        self.item_sets_payload = dict(item_sets_payload)
        self.deleted_page_ids: list[int] = []
        self.created_pages: list[dict] = []
        self.put_item_sets_payloads: list[dict] = []

    def request(self, method: str, endpoint: str, json_data: dict | None = None):
        method = method.upper()
        if method == "GET" and endpoint == "/lol-summoner/v1/current-summoner":
            return 200, {"summonerId": 999, "gameName": "TestPlayer", "tagLine": "TR1"}
        if method == "GET" and endpoint == "/lol-perks/v1/pages":
            return 200, list(self.pages)
        if method == "DELETE" and endpoint.startswith("/lol-perks/v1/pages/"):
            page_id = int(endpoint.rsplit("/", 1)[-1])
            self.deleted_page_ids.append(page_id)
            self.pages = [p for p in self.pages if p.get("id") != page_id]
            return 200, {}
        if method == "POST" and endpoint == "/lol-perks/v1/pages":
            assert json_data is not None
            self.created_pages.append(json_data)
            new_page = dict(json_data, id=777, isEditable=True, isDeletable=True)
            self.pages.append(new_page)
            return 200, new_page
        if method == "GET" and endpoint == "/lol-item-sets/v1/item-sets/999/sets":
            return 200, dict(self.item_sets_payload)
        if method == "PUT" and endpoint == "/lol-item-sets/v1/item-sets/999/sets":
            assert json_data is not None
            self.put_item_sets_payloads.append(json_data)
            self.item_sets_payload = dict(json_data)
            return 200, json_data
        raise AssertionError(f"Unexpected call: {method} {endpoint}")


def test_resolve_summoner_spells():
    # DeepLoL sends [14 (Ignite), 4 (Flash)]
    # When user prefers Flash on F: spell1 (D) = 14, spell2 (F) = 4
    assert resolve_summoner_spells([14, 4], flash_key="F") == (14, 4)
    # When user prefers Flash on D: spell1 (D) = 4, spell2 (F) = 14
    assert resolve_summoner_spells([14, 4], flash_key="D") == (4, 14)

    # When DeepLoL sends [4, 12] and user prefers Flash on F: spell1 (D) = 12, spell2 (F) = 4
    assert resolve_summoner_spells([4, 12], flash_key="F") == (12, 4)

    # Non-Flash combo [14, 12] (e.g., Camille/Shaco Ignite+TP) stays unchanged
    assert resolve_summoner_spells([14, 12], flash_key="D") == (14, 12)
    assert resolve_summoner_spells([14, 12], flash_key="F") == (14, 12)


def test_lcu_page_and_item_set_replacement():
    existing_pages = [
        {"id": 50, "name": "Preset: Mage", "isEditable": False, "isDeletable": False, "current": False},
        {"id": 101, "name": "My Custom Yasuo", "isEditable": True, "isDeletable": True, "current": True},
        {"id": 102, "name": "[DeepLoL] Zed - Middle", "isEditable": True, "isDeletable": True, "current": False},
    ]
    existing_item_sets = {
        "accountId": 12345,
        "timestamp": 1000,
        "itemSets": [
            {"uid": "user-custom-1", "title": "My Own Tank Set", "associatedChampions": [103], "blocks": []},
            {"uid": "deeplol-old", "title": "[DeepLoL] Old Ahri Set", "associatedChampions": [103], "blocks": []},
            {"uid": "deeplol-zed", "title": "[DeepLoL] Zed Set", "associatedChampions": [238], "blocks": []},
        ],
    }

    fake = FakeLCUTransport(existing_pages, existing_item_sets)
    client = LCUClient(transport_override=fake.request)

    sample_build = NormalizedBuild(
        label="Meta #1",
        champion_id=103,
        champion_name="Ahri",
        lane="Middle",
        games=1500,
        win_rate=0.52,
        pick_rate=0.60,
        runes=RunePageData(
            primary_style_id=8100,
            sub_style_id=8200,
            selected_perk_ids=[8112, 8139, 8140, 8106, 8226, 8210, 5005, 5008, 5001],
        ),
        item_blocks=[
            ItemBlockData(title="Başlangıç & Çizme", item_ids=[1056, 2003, 2003, 3020]),
            ItemBlockData(title="Çekirdek Eşyalar", item_ids=[3118, 4645, 3157]),
        ],
        spells=[14, 4],
    )

    client.import_rune_page(sample_build)
    # Must only delete the [DeepLoL] page (id=102) and NOT delete the user's "My Custom Yasuo" page (id=101)
    assert fake.deleted_page_ids == [102]
    assert len(fake.created_pages) == 1
    assert fake.created_pages[0]["name"] == "[DeepLoL] Ahri - Middle"
    assert fake.created_pages[0]["selectedPerkIds"] == [8112, 8139, 8140, 8106, 8226, 8210, 5005, 5008, 5001]

    client.import_item_set(sample_build, summoner_id=999)
    assert len(fake.put_item_sets_payloads) == 1
    saved_sets = fake.put_item_sets_payloads[0]["itemSets"]
    titles = [s["title"] for s in saved_sets]
    # User's own set and other champion's set preserved, old Ahri [DeepLoL] set replaced
    assert "My Own Tank Set" in titles
    assert "[DeepLoL] Zed Set" in titles
    assert "[DeepLoL] Old Ahri Set" not in titles
    assert "[DeepLoL] Ahri - Middle" in titles

    # Check item count aggregation (two 2003 potions combined into count=2)
    ahri_set = next(s for s in saved_sets if s["title"] == "[DeepLoL] Ahri - Middle")
    starter_items = ahri_set["blocks"][0]["items"]
    potion_entry = next(i for i in starter_items if i["id"] == "2003")
    assert potion_entry["count"] == 2
