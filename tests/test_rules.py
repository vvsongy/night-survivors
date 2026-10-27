"""Tests for rules.py only. They read the numbers from data/game.json, so changing a
number in the json does not need a change here."""

import math
import random
import unittest
from copy import deepcopy

import rules


def quiet_config():
    """The real numbers, but nothing spawns, so each test controls the enemies itself."""
    config = deepcopy(rules.load_config())
    for phase in config["spawning"]["phases"]:
        phase["minimum"] = 0
    return config


def tough_bats(config):
    """Bats that stand still, cannot hurt the hero and take many hits, so one weapon
    can be measured on its own."""
    config["enemies"]["bat"]["speed"] = 0
    config["enemies"]["bat"]["damage"] = 0
    config["enemies"]["bat"]["hp"] = 1000
    return config


def place_enemy(world, x, y):
    return place_kind(world, "bat", x, y)


def place_kind(world, kind, x, y):
    stats = world.config["enemies"][kind]
    enemy = rules.Enemy(kind, stats, x, y)
    world.enemies.append(enemy)
    return enemy


def seconds(value):
    """How many fixed steps make up this many seconds."""
    return round(value / rules.FIXED_STEP)


def apply_card(world, kind, id_, level):
    """Give the world one card and take it, like a click on the level-up screen."""
    world.state = "level_up"
    world._pending_levels = 1
    world.cards = [{"kind": kind, "id": id_, "level": level, "label": "", "text": ""}]
    world.choose_card(0)


class SpawningTest(unittest.TestCase):
    def test_spawns_up_to_the_limit_each_second(self):
        config = rules.load_config()
        world = rules.World(config, random.Random(1))
        for _ in range(round(1.0 / rules.FIXED_STEP)):
            world.step()
        self.assertEqual(len(world.enemies), config["spawning"]["max_per_check"])

    def test_enemy_count_rises_to_the_minimum(self):
        config = rules.load_config()
        world = rules.World(config, random.Random(1))
        seconds = math.ceil(config["spawning"]["phases"][0]["minimum"] / config["spawning"]["max_per_check"])
        for _ in range(round(seconds / rules.FIXED_STEP)):
            world.step()
        self.assertEqual(len(world.enemies), config["spawning"]["phases"][0]["minimum"])

    def test_enemies_appear_on_a_circle_around_the_hero(self):
        config = rules.load_config()
        world = rules.World(config, random.Random(2))
        for _ in range(round(1.0 / rules.FIXED_STEP)):
            world.step()
        for enemy in world.enemies:
            dist = math.hypot(enemy.x - world.hero_x, enemy.y - world.hero_y)
            self.assertAlmostEqual(dist, config["spawning"]["spawn_radius"], places=6)

    def test_never_more_than_the_cap_alive(self):
        config = rules.load_config()
        for phase in config["spawning"]["phases"]:
            phase["minimum"] = config["spawning"]["max_alive"] + 20
        config["enemies"]["bat"]["damage"] = 0
        config["weapons"]["spark_wand"]["base"]["shots"] = 0
        world = rules.World(config, random.Random(3))
        for _ in range(round(16.0 / rules.FIXED_STEP)):
            world.step()
        self.assertEqual(len(world.enemies), config["spawning"]["max_alive"])

    def test_enemies_too_far_away_are_removed(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(4))
        place_enemy(world, config["spawning"]["despawn_radius"] + 1, 0.0)
        world.step()
        self.assertEqual(world.enemies, [])


class MovementTest(unittest.TestCase):
    def test_hero_walks_towards_the_target(self):
        world = rules.World(quiet_config(), random.Random(5))
        world.set_move_target(300.0, 0.0)
        for _ in range(60):
            world.step()
        self.assertAlmostEqual(world.hero_x, world.config["hero"]["speed"], places=4)
        self.assertAlmostEqual(world.hero_y, 0.0, places=6)

    def test_hero_stops_short_of_the_target_by_the_deadzone(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(12))
        world.set_move_target(120.0, 0.0)
        for _ in range(60):
            world.step()
        self.assertAlmostEqual(world.hero_x, 120.0 - config["screen"]["mouse_deadzone"], places=4)

    def test_hero_stays_still_inside_the_deadzone(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(6))
        world.set_move_target(config["screen"]["mouse_deadzone"] - 1, 0.0)
        for _ in range(60):
            world.step()
        self.assertEqual((world.hero_x, world.hero_y), (0.0, 0.0))


class DamageTest(unittest.TestCase):
    def test_touching_an_enemy_hurts_once_per_half_second(self):
        config = rules.load_config()
        bat_damage = config["enemies"]["bat"]["damage"]
        world = rules.World(quiet_config(), random.Random(7))
        place_enemy(world, 0.0, 0.0)
        for _ in range(round(0.25 / rules.FIXED_STEP)):
            world.step()
        self.assertAlmostEqual(world.hp, world.max_hp - bat_damage, places=6)
        for _ in range(round(0.3 / rules.FIXED_STEP)):
            world.step()
        self.assertAlmostEqual(world.hp, world.max_hp - 2 * bat_damage, places=6)

    def test_hero_dies_makes_game_over(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(8))
        world.hp = config["enemies"]["bat"]["damage"]
        place_enemy(world, 0.0, 0.0)
        world.step()
        self.assertEqual(world.state, "game_over")
        self.assertEqual(world.hp, 0.0)
        elapsed = world.elapsed
        for _ in range(60):
            world.step()
        self.assertEqual(world.elapsed, elapsed)


class SparkWandTest(unittest.TestCase):
    def test_sparks_kill_and_count_the_kill(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(9))
        place_enemy(world, 100.0, 0.0)
        for _ in range(round(1.5 / rules.FIXED_STEP)):
            world.step()
        self.assertEqual(world.enemies, [])
        self.assertEqual(world.kills, 1)
        self.assertAlmostEqual(world.hp, world.max_hp, places=6)

    def test_wand_waits_for_the_interval_and_a_target(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(10))
        for _ in range(60):
            world.step()
        self.assertEqual(world.sparks, [])
        place_enemy(world, 0.0, 150.0)
        world.step()
        self.assertEqual(len(world.sparks), 1)
        for _ in range(round(config["weapons"]["spark_wand"]["base"]["interval"] / rules.FIXED_STEP) - 1):
            world.step()
        self.assertEqual(world.sparks, [])

    def test_wand_ignores_enemies_outside_its_range(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(11))
        place_enemy(world, config["weapons"]["spark_wand"]["base"]["target_range"] + 100, 0.0)
        for _ in range(20):
            world.step()
        self.assertEqual(world.sparks, [])


class GemTest(unittest.TestCase):
    def test_a_dead_enemy_drops_a_gem_worth_its_xp(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(20))
        world.weapons = {"spark_wand": 1}
        place_enemy(world, 100.0, 0.0)
        for _ in range(round(1.5 / rules.FIXED_STEP)):
            world.step()
        self.assertEqual(world.kills, 1)
        self.assertEqual(len(world.gems), 1)
        self.assertEqual(world.gems[0].xp, config["enemies"]["bat"]["xp"])

    def test_gems_inside_the_magnet_radius_fly_to_the_hero(self):
        world = rules.World(quiet_config(), random.Random(21))
        world.weapons = {}
        world.gems.append(rules.Gem(world.magnet_radius - 10, 0.0, 1))
        for _ in range(15):
            world.step()
        self.assertEqual(world.gems, [])
        self.assertEqual(world.xp, 1)

    def test_gems_outside_the_magnet_radius_wait(self):
        world = rules.World(quiet_config(), random.Random(22))
        world.weapons = {}
        far = world.magnet_radius + 100
        world.gems.append(rules.Gem(far, 0.0, 1))
        for _ in range(60):
            world.step()
        self.assertAlmostEqual(world.gems[0].x, far, places=6)
        self.assertEqual(world.xp, 0)

    def test_enough_xp_levels_up_and_offers_three_cards(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(23))
        world.weapons = {}
        for _ in range(config["level_up"]["xp_first"]):
            world.gems.append(rules.Gem(0.0, 0.0, 1))
        world.step()
        self.assertEqual(world.level, 2)
        self.assertEqual(world.xp, 0)
        self.assertEqual(world.state, "level_up")
        self.assertEqual(len(world.cards), config["level_up"]["cards"])
        world.choose_card(0)
        self.assertEqual(world.state, "running")

    def test_xp_for_the_next_level_grows_every_level(self):
        config = rules.load_config()
        levels = config["level_up"]
        world = rules.World(quiet_config(), random.Random(24))
        for level in (1, 2, 3):
            world.level = level
            self.assertEqual(
                world.xp_needed(), levels["xp_first"] + levels["xp_step"] * (level - 1)
            )


class CardTest(unittest.TestCase):
    def test_a_card_raises_a_weapon_level(self):
        world = rules.World(quiet_config(), random.Random(25))
        apply_card(world, "weapon", "spin_blades", 1)
        self.assertEqual(world.weapons["spin_blades"], 1)
        apply_card(world, "weapon", "spin_blades", 2)
        self.assertEqual(world.weapons["spin_blades"], 2)
        self.assertEqual(world.state, "running")

    def test_passive_items_change_speed_max_hp_and_magnet(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(26))
        apply_card(world, "item", "swift_boots", 1)
        self.assertAlmostEqual(
            world.speed, config["hero"]["speed"] * 1.1, places=6
        )
        world.hp = 50
        apply_card(world, "item", "big_heart", 1)
        self.assertEqual(world.max_hp, config["hero"]["hp"] + 20)
        self.assertEqual(world.hp, 70)
        apply_card(world, "item", "magnet", 2)
        self.assertEqual(
            world.magnet_radius, config["hero"]["gem_magnet_radius"] + 2 * 30
        )

    def test_a_fourth_weapon_is_never_offered(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(31))
        world.weapons = {kind: 1 for kind in config["weapons"]}
        world.gems.append(rules.Gem(0.0, 0.0, world.xp_needed()))
        world.step()
        self.assertEqual(len(world.weapons), config["level_up"]["max_weapons"])
        brand_new = [card for card in world.cards if card["kind"] == "weapon" and card["level"] == 1]
        self.assertEqual(brand_new, [])

    def test_only_heal_cards_are_left_when_everything_is_maxed(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(27))
        world.weapons = {kind: config["level_up"]["max_level"] for kind in config["weapons"]}
        world.items = {kind: config["level_up"]["max_level"] for kind in config["items"]}
        world.hp = 50
        world.gems.append(rules.Gem(0.0, 0.0, world.xp_needed()))
        world.step()
        self.assertEqual(world.state, "level_up")
        self.assertEqual({card["kind"] for card in world.cards}, {"heal"})
        world.choose_card(0)
        self.assertEqual(world.hp, 50 + config["level_up"]["heal"])


class WeaponTest(unittest.TestCase):
    def test_weapon_levels_add_damage_speed_and_count(self):
        config = rules.load_config()
        wand = config["weapons"]["spark_wand"]
        world = rules.World(quiet_config(), random.Random(28))
        self.assertEqual(world.weapon_stat("spark_wand", "damage"), wand["base"]["damage"])
        world.weapons["spark_wand"] = 3
        self.assertEqual(
            world.weapon_stat("spark_wand", "damage"),
            wand["base"]["damage"] + 2 * wand["per_level"]["damage"],
        )
        self.assertEqual(
            world.weapon_stat("spark_wand", "interval"),
            wand["base"]["interval"] + 2 * wand["per_level"]["interval"],
        )
        self.assertEqual(world.weapon_stat("spark_wand", "shots"), wand["base"]["shots"] + 1)
        world.weapons["spark_wand"] = 5
        self.assertEqual(world.weapon_stat("spark_wand", "shots"), wand["base"]["shots"] + 2)

    def test_spin_blades_hit_once_per_interval_per_blade(self):
        config = tough_bats(quiet_config())
        orbit = config["weapons"]["spin_blades"]["base"]
        world = rules.World(config, random.Random(29))
        world.weapons = {"spin_blades": 1}
        place_enemy(world, orbit["orbit_radius"], 0.0)
        world.step()
        self.assertEqual(world.enemies[0].hp, 1000 - orbit["damage"])
        for _ in range(24):
            world.step()
        self.assertEqual(world.enemies[0].hp, 1000 - orbit["damage"])
        for _ in range(21):
            world.step()
        self.assertEqual(world.enemies[0].hp, 1000 - 2 * orbit["damage"])
        self.assertEqual(len(world.blade_points), orbit["blades"])

    def test_holy_ring_hurts_every_enemy_inside_the_circle(self):
        config = tough_bats(quiet_config())
        ring = config["weapons"]["holy_ring"]
        world = rules.World(config, random.Random(30))
        world.weapons = {"holy_ring": 1}
        inside = place_enemy(world, ring["base"]["radius"] - 20, 0.0)
        outside = place_enemy(world, ring["base"]["radius"] + 150, 0.0)
        for _ in range(60):
            world.step()
        self.assertEqual(inside.hp, 1000 - 2 * ring["base"]["damage"])
        self.assertEqual(outside.hp, 1000)


class WaveTest(unittest.TestCase):
    def test_the_run_is_won_at_the_goal_time(self):
        config = quiet_config()
        config["run"]["duration"] = 3.0
        world = rules.World(config, random.Random(40))
        world.weapons = {}
        for _ in range(seconds(3.0)):
            world.step()
        self.assertEqual(world.state, "victory")
        self.assertEqual(world.elapsed, 3.0)
        world.step()
        self.assertEqual(world.elapsed, 3.0)

    def test_each_wave_uses_the_kinds_written_in_the_table(self):
        config = quiet_config()
        for phase in config["spawning"]["phases"]:
            if phase["from"] == 45:
                phase["minimum"] = config["spawning"]["max_per_check"]
        world = rules.World(config, random.Random(41))
        world.weapons = {}
        for _ in range(seconds(46.0)):
            world.step()
        kinds = {enemy.kind for enemy in world.enemies}
        self.assertEqual(len(world.enemies), config["spawning"]["max_per_check"])
        self.assertTrue(kinds)
        self.assertTrue(kinds <= {"slime", "ghost"})

    def test_the_boss_appears_only_once(self):
        config = quiet_config()
        config["enemies"]["demon"]["damage"] = 0
        world = rules.World(config, random.Random(42))
        world.weapons = {}
        for _ in range(seconds(100.0)):
            world.step()
        self.assertEqual([enemy.kind for enemy in world.enemies], ["demon"])
        self.assertTrue(world.enemies[0].boss)

    def test_the_boss_is_pulled_back_instead_of_being_given_up(self):
        config = quiet_config()
        world = rules.World(config, random.Random(43))
        world.weapons = {}
        place_kind(world, "demon", config["spawning"]["boss_return_radius"] + 300, 0.0)
        world.step()
        self.assertEqual(len(world.enemies), 1)
        dist = math.hypot(world.enemies[0].x, world.enemies[0].y)
        # Back on the spawn circle, then one step of its own walk.
        self.assertLessEqual(dist, config["spawning"]["spawn_radius"])
        self.assertGreater(dist, config["spawning"]["spawn_radius"] - 5)

    def test_a_slime_drops_a_bigger_gem(self):
        config = quiet_config()
        config["enemies"]["slime"]["speed"] = 0
        config["enemies"]["slime"]["damage"] = 0
        world = rules.World(config, random.Random(44))
        world.weapons = {"spark_wand": 1}
        place_kind(world, "slime", 100.0, 0.0)
        for _ in range(seconds(4.0)):
            world.step()
        self.assertEqual(world.kills, 1)
        self.assertEqual([drop.xp for drop in world.gems], [config["enemies"]["slime"]["xp"]])

    def test_the_boss_drops_no_gem(self):
        config = quiet_config()
        config["enemies"]["demon"]["hp"] = 5
        config["enemies"]["demon"]["speed"] = 0
        config["enemies"]["demon"]["damage"] = 0
        world = rules.World(config, random.Random(45))
        world.weapons = {"spark_wand": 1}
        place_kind(world, "demon", 100.0, 0.0)
        for _ in range(seconds(2.0)):
            world.step()
        self.assertEqual(world.kills, 1)
        self.assertEqual(world.gems, [])

    def test_the_ghost_is_faster_than_the_hero_and_the_slime_slower(self):
        config = rules.load_config()
        hero = config["hero"]["speed"]
        self.assertGreater(config["enemies"]["ghost"]["speed"], hero)
        self.assertLess(config["enemies"]["slime"]["speed"], hero)


class EventTest(unittest.TestCase):
    """step() tells the window what happened, so it can play a sound or show an effect."""

    def gather(self, world, count):
        seen = []
        for _ in range(count):
            seen.extend(world.step())
        return seen

    def still_bats(self):
        config = quiet_config()
        config["enemies"]["bat"]["speed"] = 0
        return config

    def test_a_hit_and_a_death_are_reported(self):
        config = rules.load_config()
        world = rules.World(self.still_bats(), random.Random(50))
        place_enemy(world, 100.0, 0.0)
        events = self.gather(world, seconds(1.5))
        hits = [event for event in events if event[0] == "enemy_hit"]
        deaths = [event for event in events if event[0] == "enemy_died"]
        self.assertEqual(len(deaths), 1)
        self.assertEqual(deaths[0][1:], (100.0, 0.0))
        self.assertEqual(hits[0][3], config["weapons"]["spark_wand"]["base"]["damage"])
        for event in hits:
            self.assertGreater(event[1], 60.0)
            self.assertLess(event[1], 100.0)

    def test_getting_hurt_and_dying_are_reported(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(51))
        world.weapons = {}
        world.hp = config["enemies"]["bat"]["damage"]
        place_enemy(world, 0.0, 0.0)
        events = world.step()
        self.assertEqual([event[0] for event in events], ["hero_hurt", "game_over"])
        self.assertEqual(events[0][1], config["enemies"]["bat"]["damage"])
        for _ in range(30):
            self.assertEqual(world.step(), [])

    def test_the_ring_reports_every_enemy_it_hurts(self):
        config = tough_bats(self.still_bats())
        ring = config["weapons"]["holy_ring"]["base"]
        world = rules.World(config, random.Random(52))
        world.weapons = {"holy_ring": 1}
        place_enemy(world, ring["radius"] - 20, 0.0)
        place_enemy(world, -ring["radius"] + 20, 0.0)
        world.step()
        self.assertEqual(len([event for event in world.events if event[0] == "enemy_hit"]), 2)

    def test_a_gem_and_a_level_up_are_reported(self):
        config = rules.load_config()
        world = rules.World(quiet_config(), random.Random(53))
        world.weapons = {}
        for _ in range(config["level_up"]["xp_first"]):
            world.gems.append(rules.Gem(0.0, 0.0, 1))
        kinds = [event[0] for event in world.step()]
        self.assertEqual(kinds.count("gem_taken"), config["level_up"]["xp_first"])
        self.assertEqual(kinds.count("level_up"), 1)

    def test_winning_is_reported(self):
        config = self.still_bats()
        config["run"]["duration"] = 1.0
        world = rules.World(config, random.Random(54))
        world.weapons = {}
        events = self.gather(world, seconds(1.0))
        self.assertEqual(events[-1], ("victory",))
        self.assertEqual(world.step(), [])


if __name__ == "__main__":
    unittest.main()
