"""The rules of Night Survivors. No pygame here: only numbers and plain Python.

The world is endless, so everything is stored in world coordinates around the hero,
who starts at (0, 0). One call to World.step() advances the game by FIXED_STEP seconds
and returns the events for that step, which the window turns into sounds and effects.
Every number comes from data/game.json, so the design can be changed without code.
"""

import json
import math
import os
import random

FIXED_STEP = 1.0 / 60.0

# Float sums drift a hair under whole seconds, which would skip a spawn check.
_EPS = 1e-9

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "game.json")


def load_config(path=DATA_PATH):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


class Enemy:
    def __init__(self, kind, stats, x, y):
        self.kind = kind
        self.x = x
        self.y = y
        self.hp = float(stats["hp"])
        self.max_hp = float(stats["hp"])
        self.speed = float(stats["speed"])
        self.damage = float(stats["damage"])
        self.xp = float(stats["xp"])
        self.radius = float(stats["radius"])
        self.boss = bool(stats.get("boss"))
        self.hit_cooldown = 0.0
        # (weapon, blade number) -> seconds until this blade may hurt this enemy again
        self.blade_cooldowns = {}


class Spark:
    def __init__(self, x, y, vx, vy, damage, radius, max_distance):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.damage = damage
        self.radius = radius
        self.max_distance = max_distance


class Gem:
    def __init__(self, x, y, xp):
        self.x = x
        self.y = y
        self.xp = xp


class World:
    def __init__(self, config=None, rng=None):
        self.config = load_config() if config is None else config
        self.rng = random.Random() if rng is None else rng

        hero = self.config["hero"]
        self.hero_x = 0.0
        self.hero_y = 0.0
        self.radius = float(hero["hit_radius"])

        self.weapons = dict(self.config["start_weapons"])
        self.items = {}
        self.level = 1
        self.xp = 0
        self.kills = 0
        self.elapsed = 0.0
        self.state = "running"
        self.cards = []

        self.enemies = []
        self.sparks = []
        self.gems = []
        self.blade_points = []

        self.move_target = None
        self.events = []
        self._spawn_timer = 0.0
        self._bosses_spawned = set()
        self._cooldowns = {kind: 0.0 for kind in self.weapons}
        self._blade_angle = 0.0
        self._pending_levels = 0

        self.hp = 0.0
        self.max_hp = 0.0
        self.speed = 0.0
        self.magnet_radius = 0.0
        self._recompute_stats()
        self.hp = self.max_hp

    # ---------- what the player and the screen tell the rules ----------

    def set_move_target(self, x, y):
        """Walk towards this world point; None means stand still."""
        self.move_target = None if x is None else (float(x), float(y))

    def choose_card(self, index):
        """Take one of the level-up cards, counting from 0."""
        if self.state != "level_up" or not 0 <= index < len(self.cards):
            return
        card = self.cards[index]
        if card["kind"] == "heal":
            self.hp = min(self.max_hp, self.hp + self.config["level_up"]["heal"])
        elif card["kind"] == "weapon":
            self.weapons[card["id"]] = card["level"]
            self._cooldowns.setdefault(card["id"], 0.0)
        else:
            self.items[card["id"]] = card["level"]
            self._recompute_stats()
            heal = self.config["items"][card["id"]]["per_level"].get("heal", 0)
            self.hp = min(self.max_hp, self.hp + heal)
        self._pending_levels -= 1
        self.cards = []
        if self._pending_levels > 0:
            self._offer_cards()
        else:
            self.state = "running"

    # ---------- the fixed time step ----------

    def step(self):
        """Advance one step and return what happened, as plain tuples.

        ("enemy_hit", x, y, damage), ("enemy_died", x, y), ("gem_taken", x, y, xp),
        ("hero_hurt", damage), ("level_up",), ("game_over",), ("victory",)
        """
        self.events = []
        if self.state != "running":
            return self.events
        self.elapsed += FIXED_STEP
        if self.elapsed + _EPS >= self.config["run"]["duration"]:
            self.elapsed = self.config["run"]["duration"]
            self.state = "victory"
            self.events.append(("victory",))
            return self.events
        self._move_hero()
        self._update_enemies()
        if self.state != "running":
            return self.events
        self._update_weapons()
        self._update_sparks()
        self._collect_dead()
        self._update_gems()
        self._update_spawning()
        return self.events

    def _move_hero(self):
        if self.move_target is None:
            return
        deadzone = self.config["screen"]["mouse_deadzone"]
        target_x, target_y = self.move_target
        dist = _distance(self.hero_x, self.hero_y, target_x, target_y)
        if dist <= deadzone:
            return
        stride = min(self.speed * FIXED_STEP, dist)
        self.hero_x += (target_x - self.hero_x) / dist * stride
        self.hero_y += (target_y - self.hero_y) / dist * stride

    # ---------- enemies ----------

    def _phase(self):
        phases = self.config["spawning"]["phases"]
        current = phases[0]
        for phase in phases:
            if self.elapsed + _EPS >= phase["from"]:
                current = phase
        return current

    def _known_kinds(self, phase):
        kinds = self.config["enemies"]
        return [kind for kind in phase["types"] if kind in kinds]

    def _update_spawning(self):
        spawning = self.config["spawning"]
        self._spawn_timer += FIXED_STEP
        if self._spawn_timer + _EPS < spawning["check_seconds"]:
            return
        self._spawn_timer -= spawning["check_seconds"]
        self._spawn_batch()
        self._spawn_boss()

    def _spawn_at(self, kind, angle):
        spawning = self.config["spawning"]
        self.enemies.append(
            Enemy(
                kind,
                self.config["enemies"][kind],
                self.hero_x + math.cos(angle) * spawning["spawn_radius"],
                self.hero_y + math.sin(angle) * spawning["spawn_radius"],
            )
        )

    def _spawn_batch(self):
        spawning = self.config["spawning"]
        kinds = self._known_kinds(self._phase())
        if not kinds:
            return
        alive = len(self.enemies)
        count = max(
            0,
            min(
                self._phase()["minimum"] - alive,
                spawning["max_per_check"],
                spawning["max_alive"] - alive,
            ),
        )
        for _ in range(count):
            self._spawn_at(self.rng.choice(kinds), self.rng.random() * math.tau)

    def _spawn_boss(self):
        """The boss of a wave appears once, and only once, for the whole run."""
        kind = self._phase().get("boss")
        if not kind or kind in self._bosses_spawned:
            return
        if len(self.enemies) >= self.config["spawning"]["max_alive"]:
            return
        self._bosses_spawned.add(kind)
        self._spawn_at(kind, self.rng.random() * math.tau)

    def _update_enemies(self):
        spawning = self.config["spawning"]
        survivors = []
        for enemy in self.enemies:
            dist = _distance(enemy.x, enemy.y, self.hero_x, self.hero_y)
            if enemy.boss:
                # The boss is never given up on: it walks back onto the spawn circle.
                if dist > spawning["boss_return_radius"]:
                    pull = spawning["spawn_radius"] / dist
                    enemy.x = self.hero_x + (enemy.x - self.hero_x) * pull
                    enemy.y = self.hero_y + (enemy.y - self.hero_y) * pull
                    dist = spawning["spawn_radius"]
            elif dist > spawning["despawn_radius"]:
                continue
            enemy.hit_cooldown = max(0.0, enemy.hit_cooldown - FIXED_STEP)
            for key in list(enemy.blade_cooldowns):
                enemy.blade_cooldowns[key] = max(0.0, enemy.blade_cooldowns[key] - FIXED_STEP)
            stride = enemy.speed * FIXED_STEP
            if dist > 0:
                enemy.x += (self.hero_x - enemy.x) / dist * stride
                enemy.y += (self.hero_y - enemy.y) / dist * stride
            if dist <= enemy.radius + self.radius and enemy.hit_cooldown <= 0.0:
                self.hp -= enemy.damage
                enemy.hit_cooldown = spawning["enemy_hit_interval"]
                self.events.append(("hero_hurt", enemy.damage))
                if self.hp <= 0:
                    self.hp = 0.0
                    self.state = "game_over"
                    self.events.append(("game_over",))
                    return
            survivors.append(enemy)
        self.enemies = survivors

    def _collect_dead(self):
        alive = []
        for enemy in self.enemies:
            if enemy.hp > 0:
                alive.append(enemy)
                continue
            self.kills += 1
            self.events.append(("enemy_died", enemy.x, enemy.y))
            if enemy.xp > 0:
                self.gems.append(Gem(enemy.x, enemy.y, enemy.xp))
        self.enemies = alive

    # ---------- weapons ----------

    def weapon_stat(self, kind, name):
        """One number for one weapon at its present level."""
        weapon = self.config["weapons"][kind]
        level = self.weapons[kind]
        value = weapon["base"].get(name, 0) + weapon.get("per_level", {}).get(name, 0) * (level - 1)
        if name == weapon.get("count_stat"):
            value += sum(1 for at in weapon.get("extra_count_at", []) if level >= at)
        return value

    def _update_weapons(self):
        for kind in self.weapons:
            self._cooldowns.setdefault(kind, 0.0)
            behaviour = self.config["weapons"][kind]["behaviour"]
            if behaviour == "projectile":
                self._update_projectile(kind)
            elif behaviour == "orbit":
                self._update_orbit(kind)
            elif behaviour == "aura":
                self._update_aura(kind)

    def _nearest_enemies(self, limit, range_):
        inside = [
            (enemy, _distance(self.hero_x, self.hero_y, enemy.x, enemy.y))
            for enemy in self.enemies
            if enemy.hp > 0
        ]
        inside = [pair for pair in inside if pair[1] <= range_]
        inside.sort(key=lambda pair: pair[1])
        return [enemy for enemy, _ in inside[:limit]]

    def _update_projectile(self, kind):
        stats = {name: self.weapon_stat(kind, name) for name in self.config["weapons"][kind]["base"]}
        self._cooldowns[kind] = max(0.0, self._cooldowns[kind] - FIXED_STEP)
        if self._cooldowns[kind] > 0.0:
            return
        targets = self._nearest_enemies(stats["shots"], stats["target_range"])
        if not targets:
            return
        self._cooldowns[kind] = stats["interval"]
        for enemy in targets:
            dist = _distance(self.hero_x, self.hero_y, enemy.x, enemy.y)
            if dist <= 0:
                continue
            self.sparks.append(
                Spark(
                    self.hero_x,
                    self.hero_y,
                    (enemy.x - self.hero_x) / dist * stats["speed"],
                    (enemy.y - self.hero_y) / dist * stats["speed"],
                    stats["damage"],
                    stats["radius"],
                    stats["max_distance"],
                )
            )

    def _update_sparks(self):
        still_flying = []
        for spark in self.sparks:
            spark.x += spark.vx * FIXED_STEP
            spark.y += spark.vy * FIXED_STEP
            if _distance(self.hero_x, self.hero_y, spark.x, spark.y) > spark.max_distance:
                continue
            hit = self._take_hit(spark)
            if not hit:
                still_flying.append(spark)
        self.sparks = still_flying

    def _take_hit(self, spark):
        for enemy in self.enemies:
            if enemy.hp <= 0:
                continue
            if _distance(spark.x, spark.y, enemy.x, enemy.y) <= spark.radius + enemy.radius:
                enemy.hp -= spark.damage
                self.events.append(("enemy_hit", spark.x, spark.y, spark.damage))
                return True
        return False

    def _update_orbit(self, kind):
        stats = {name: self.weapon_stat(kind, name) for name in self.config["weapons"][kind]["base"]}
        self._blade_angle = (self._blade_angle + math.tau * FIXED_STEP / stats["turn_seconds"]) % math.tau
        self.blade_points = []
        for blade in range(int(stats["blades"])):
            angle = self._blade_angle + blade * math.tau / stats["blades"]
            x = self.hero_x + math.cos(angle) * stats["orbit_radius"]
            y = self.hero_y + math.sin(angle) * stats["orbit_radius"]
            self.blade_points.append((x, y))
            key = (kind, blade)
            for enemy in self.enemies:
                if enemy.hp <= 0:
                    continue
                if _distance(x, y, enemy.x, enemy.y) > stats["radius"] + enemy.radius:
                    continue
                if enemy.blade_cooldowns.get(key, 0.0) > 0.0:
                    continue
                enemy.hp -= stats["damage"]
                enemy.blade_cooldowns[key] = stats["hit_interval"]
                self.events.append(("enemy_hit", enemy.x, enemy.y, stats["damage"]))

    def _update_aura(self, kind):
        stats = {name: self.weapon_stat(kind, name) for name in self.config["weapons"][kind]["base"]}
        self._cooldowns[kind] = max(0.0, self._cooldowns[kind] - FIXED_STEP)
        if self._cooldowns[kind] > 0.0:
            return
        inside = [enemy for enemy in self.enemies if enemy.hp > 0 and _distance(
            self.hero_x, self.hero_y, enemy.x, enemy.y
        ) <= stats["radius"] + enemy.radius]
        if not inside:
            return
        self._cooldowns[kind] = stats["interval"]
        for enemy in inside:
            enemy.hp -= stats["damage"]
            self.events.append(("enemy_hit", enemy.x, enemy.y, stats["damage"]))

    # ---------- gems, XP and level-up cards ----------

    def _update_gems(self):
        gem = self.config["gem"]
        kept = []
        for drop in self.gems:
            dist = _distance(self.hero_x, self.hero_y, drop.x, drop.y)
            if dist <= self.radius + gem["radius"]:
                self.events.append(("gem_taken", drop.x, drop.y, drop.xp))
                self._add_xp(drop.xp)
                continue
            if dist <= self.magnet_radius:
                stride = min(gem["speed"] * FIXED_STEP, dist)
                drop.x += (self.hero_x - drop.x) / dist * stride
                drop.y += (self.hero_y - drop.y) / dist * stride
            kept.append(drop)
        self.gems = kept

    def xp_needed(self):
        levels = self.config["level_up"]
        return levels["xp_first"] + levels["xp_step"] * (self.level - 1)

    def _add_xp(self, amount):
        before = self.level
        self.xp += amount
        while self.xp >= self.xp_needed():
            self.xp -= self.xp_needed()
            self.level += 1
            self._pending_levels += 1
        if self.level > before:
            self.events.append(("level_up",))
        if self._pending_levels > 0:
            self.state = "level_up"
            self._offer_cards()

    def _recompute_stats(self):
        hero = self.config["hero"]
        self.speed = hero["speed"] * (1 + self._item_total("walk_speed_percent") / 100.0)
        self.magnet_radius = hero["gem_magnet_radius"] + self._item_total("magnet_radius")
        self.max_hp = hero["hp"] + self._item_total("max_hp")
        self.hp = min(self.hp, self.max_hp)

    def _item_total(self, name):
        items = self.config["items"]
        return sum(
            level * items[kind]["per_level"].get(name, 0) for kind, level in self.items.items()
        )

    def _card_options(self):
        levels = self.config["level_up"]
        options = []
        for kind, level in self.weapons.items():
            if level < levels["max_level"]:
                options.append(("weapon", kind, level + 1))
        if len(self.weapons) < levels["max_weapons"]:
            for kind in self.config["weapons"]:
                if kind not in self.weapons:
                    options.append(("weapon", kind, 1))
        for kind, level in self.items.items():
            if level < levels["max_level"]:
                options.append(("item", kind, level + 1))
        for kind in self.config["items"]:
            if kind not in self.items:
                options.append(("item", kind, 1))
        return options

    def _offer_cards(self):
        levels = self.config["level_up"]
        options = self._card_options()
        self.rng.shuffle(options)
        self.cards = []
        for kind, id_, level in options[: levels["cards"]]:
            if kind == "weapon":
                info = self.config["weapons"][id_]
            else:
                info = self.config["items"][id_]
            self.cards.append(
                {"kind": kind, "id": id_, "level": level, "label": info["label"], "text": info["card_text"]}
            )
        while len(self.cards) < levels["cards"]:
            self.cards.append(
                {
                    "kind": "heal",
                    "id": "heal",
                    "level": None,
                    "label": f"Heal {levels['heal']} HP",
                    "text": levels["heal_text"],
                }
            )
