import pytest

from deeplol_importer.deeplol_client import (
    map_lcu_position_to_deeplol_lane,
    normalize_rune_perks,
    parse_deeplol_url,
)


def test_normalize_rune_perks():
    # DeepLoL returns stat_build in reverse Match-v5 alphabetical order: [defense, flex, offense]
    main_build = [8100, 8112, 8139, 8140, 8106]
    sub_build = [8200, 8226, 8210]
    stat_build = [5001, 5008, 5005]  # 5001=defense, 5008=flex, 5005=offense

    rune_page = normalize_rune_perks(main_build, sub_build, stat_build)

    assert rune_page.primary_style_id == 8100
    assert rune_page.sub_style_id == 8200
    assert rune_page.selected_perk_ids == [
        8112,
        8139,
        8140,
        8106,
        8226,
        8210,
        5005,  # offense first
        5008,  # flex second
        5001,  # defense third
    ]

    with pytest.raises(ValueError):
        normalize_rune_perks([8100, 8112], sub_build, stat_build)


def test_parse_deeplol_url_and_lane_mapping():
    parsed_mid = parse_deeplol_url("https://www.deeplol.gg/champions/ahri/build/mid?hl=en")
    assert parsed_mid.champion_slug == "ahri"
    assert parsed_mid.lane == "Middle"
    assert parsed_mid.mode == "meta"

    parsed_aram = parse_deeplol_url("https://www.deeplol.gg/champions/AurelionSol/build/aram")
    assert parsed_aram.champion_slug == "aurelionsol"
    assert parsed_aram.lane == "Aram"
    assert parsed_aram.mode == "meta"

    parsed_otp = parse_deeplol_url("https://www.deeplol.gg/champions/yasuo/mastery/top")
    assert parsed_otp.champion_slug == "yasuo"
    assert parsed_otp.lane == "Top"
    assert parsed_otp.mode == "otp"

    parsed_detail = parse_deeplol_url("https://www.deeplol.gg/champions/detail?championName=LeeSin&lane=jungle")
    assert parsed_detail.champion_slug == "leesin"
    assert parsed_detail.lane == "Jungle"
    assert parsed_detail.mode == "meta"

    with pytest.raises(ValueError):
        parse_deeplol_url("https://example.com/champions/ahri")

    assert map_lcu_position_to_deeplol_lane("utility", "CLASSIC") == "Support"
    assert map_lcu_position_to_deeplol_lane("bottom", "CLASSIC") == "Bottom"
    assert map_lcu_position_to_deeplol_lane("middle", "CLASSIC") == "Middle"
    assert map_lcu_position_to_deeplol_lane("", "ARAM") == "Aram"
    assert map_lcu_position_to_deeplol_lane("top", "ARAM") == "Aram"
