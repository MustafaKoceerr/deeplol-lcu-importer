from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunePageData:
    primary_style_id: int
    sub_style_id: int
    selected_perk_ids: list[int]


@dataclass(frozen=True)
class ItemBlockData:
    title: str
    item_ids: list[int]


@dataclass(frozen=True)
class NormalizedBuild:
    label: str
    champion_id: int
    champion_name: str
    lane: str
    games: int
    win_rate: float
    pick_rate: float
    runes: RunePageData
    item_blocks: list[ItemBlockData]
    spells: list[int]
    skill_priority: list[int] = field(default_factory=list)
    skill_order: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class OTPPlayerSummary:
    rank: int
    platform_id: str
    tier: str
    lp: int
    champion_id: int
    riot_id_name: str
    riot_id_tag_line: str
    lane: str
    games: int
    win_rate: float
    kda: float
    puu_id: str

    @property
    def display_label(self) -> str:
        tag = f"#{self.riot_id_tag_line}" if self.riot_id_tag_line else ""
        return (
            f"#{self.rank} {self.riot_id_name}{tag} "
            f"({self.tier} {self.lp} LP | %{self.win_rate * 100:.1f} WR | {self.games} Oyun)"
        )


@dataclass(frozen=True)
class ParsedDeepLoLUrl:
    champion_slug: str
    lane: str
    mode: str  # "meta" or "otp"
