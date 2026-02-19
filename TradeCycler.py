import sys
import time
import re
import threading
import queue

import minescript
from minescript import echo, execute, player_look_at, player_press_use
from minescript import player_press_attack, player_inventory, player_inventory_select_slot
from minescript import entities, getblock, screen_name, flush
from minescript import EventQueue, EventType

exit_requested = False
KEY_ESCAPE = 256


def _exit_listener_thread_fn():
    global exit_requested
    try:
        with EventQueue() as event_queue:
            event_queue.register_key_listener()
            while not exit_requested:
                try:
                    event = event_queue.get(block=True, timeout=0.5)
                except queue.Empty:
                    continue
                if getattr(event, "type", None) == EventType.KEY and getattr(event, "key", None) == KEY_ESCAPE:
                    exit_requested = True
                    break
    except Exception:
        pass


STEP = 0

def step_ok(desc):
    global STEP
    STEP += 1
    echo(f"  Step {STEP} - {desc} - OK")

def step_fail(desc, detail=""):
    global STEP
    STEP += 1
    msg = f"  Step {STEP} - {desc} - FAIL"
    if detail:
        msg += f" ({detail})"
    echo(msg)

def step_info(desc):
    echo(f"  [INFO] {desc}")


_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

def _parse_roman(s):
    s = (s or "").strip().upper()
    if not s:
        return None
    val = 0
    prev = 0
    for c in reversed(s):
        n = _ROMAN.get(c.lower(), 0)
        if n == 0:
            return None
        val += n if n >= prev else -n
        prev = n
    return val if val > 0 else None


def normalize_enchant(name):
    raw = (name or "").strip()
    if not raw:
        return None, None
    parts = raw.split()
    if len(parts) >= 2:
        level_str = parts[-1].strip()
        enchant_part = " ".join(parts[:-1]).strip()
        min_level = None
        if level_str.isdigit():
            min_level = int(level_str)
        else:
            min_level = _parse_roman(level_str)
        if min_level is not None and 1 <= min_level <= 10:
            name = enchant_part
        else:
            min_level = None
            name = raw
    else:
        min_level = None
        name = raw
    name = name.strip().lower()
    if not name:
        return None, None
    if ":" not in name:
        name = "minecraft:" + name
    return name, min_level


class _VillagerLike:
    __slots__ = ("position", "type", "nbt")
    def __init__(self, position, type_="villager", nbt=None):
        self.position = position
        self.type = type_
        self.nbt = nbt or ""


def _find_villagers_java(librarians_only=True):
    try:
        from java import JavaClass
        Minecraft = JavaClass("net.minecraft.client.Minecraft")
        mc = Minecraft.getInstance()
        if mc is None or mc.player is None:
            return []
        level = mc.level
        if level is None:
            level = getattr(mc, "world", None)
        if level is None:
            return []
        player = mc.player
        px, py, pz = player.getX(), player.getY(), player.getZ()
        r = 32.0
        try:
            AABB = JavaClass("net.minecraft.world.phys.AABB")
            box = AABB(px - r, py - r, pz - r, px + r, py + r, pz + r)
        except Exception:
            return []
        villager_class = None
        for name in (
            "net.minecraft.world.entity.npc.Villager",
            "net.minecraft.entity.passive.VillagerEntity",
        ):
            try:
                villager_class = JavaClass(name)
                break
            except Exception:
                continue
        if villager_class is None:
            return []
        try:
            entity_list = level.getEntitiesOfClass(villager_class, box)
        except Exception:
            try:
                entity_list = level.getEntities(player, box, None)
                if entity_list is not None:
                    out = []
                    it = entity_list.iterator()
                    while it.hasNext():
                        e = it.next()
                        if e is not None and villager_class.isInstance(e):
                            ex, ey, ez = e.getX(), e.getY(), e.getZ()
                            nbt_str = ""
                            try:
                                if hasattr(e, "getVillagerData"):
                                    vd = e.getVillagerData()
                                    if vd is not None:
                                        get_prof = getattr(vd, "getProfession", None) or getattr(vd, "profession", None)
                                        prof = get_prof() if callable(get_prof) else None
                                        if prof is not None:
                                            nbt_str = str(prof.toString()).lower()
                            except Exception:
                                pass
                            if librarians_only and nbt_str and "librarian" not in nbt_str:
                                continue
                            out.append(_VillagerLike((ex, ey, ez), "villager", nbt_str))
                    def dist(v):
                        vx, vy, vz = v.position[0], v.position[1], v.position[2]
                        return (vx - px) ** 2 + (vy - py) ** 2 + (vz - pz) ** 2
                    out.sort(key=dist)
                    return out
            except Exception:
                pass
            return []
        if entity_list is None or entity_list.isEmpty():
            return []
        out = []
        n = entity_list.size()
        for i in range(n):
            e = entity_list.get(i)
            if e is None:
                continue
            ex, ey, ez = e.getX(), e.getY(), e.getZ()
            nbt_str = ""
            try:
                if hasattr(e, "getVillagerData"):
                    vd = e.getVillagerData()
                    if vd is not None:
                        get_prof = getattr(vd, "getProfession", None) or getattr(vd, "profession", None)
                        prof = get_prof() if callable(get_prof) else None
                        if prof is not None:
                            nbt_str = str(prof.toString()).lower()
            except Exception:
                pass
            if librarians_only and nbt_str and "librarian" not in nbt_str:
                continue
            out.append(_VillagerLike((ex, ey, ez), "villager", nbt_str))
        def dist(v):
            vx, vy, vz = v.position[0], v.position[1], v.position[2]
            return (vx - px) ** 2 + (vy - py) ** 2 + (vz - pz) ** 2
        out.sort(key=dist)
        return out
    except Exception as e:
        step_info(f"Java villager search: {e}")
        return []


def find_closest_librarian():
    step_info("Finding nearby villagers...")
    all_villagers = []
    for type_pattern in (".*villager.*", "villager", "minecraft:villager"):
        try:
            all_villagers = entities(
                type=type_pattern,
                sort="nearest",
                limit=15,
                nbt=True,
                max_distance=64,
            )
            if all_villagers:
                break
        except Exception as e:
            step_info(f"entities(type={type_pattern!r}): {e}")
            continue
    if not all_villagers:
        try:
            nearby = entities(sort="nearest", limit=50, max_distance=64, nbt=True)
            for e in nearby or []:
                t = getattr(e, "type", None) or ""
                if "villager" in str(t).lower():
                    all_villagers.append(e)
        except Exception as e:
            step_info(f"Fallback entity search: {e}")
    if not all_villagers:
        step_info("Trying Java client-world villager search...")
        all_villagers = _find_villagers_java()
    if not all_villagers:
        step_fail("Finding villagers", "no villagers in range (try standing closer)")
        return None
    step_ok("Found villager(s)")
    for v in all_villagers:
        nbt = getattr(v, "nbt", None) or ""
        if isinstance(nbt, dict):
            nbt = str(nbt)
        if "librarian" in (nbt or "").lower():
            step_info(f"Selected librarian at {v.position}")
            return v
    v = all_villagers[0]
    step_info(f"Using closest villager at {v.position} (ensure it is a librarian)")
    return v


def open_trade_with_villager(librarian):
    if not librarian:
        return False
    p = _pos_xyz(getattr(librarian, "position", None))
    if p is None:
        step_fail("Get villager position", "invalid position")
        return False
    px, py, pz = p
    look_y = float(py) + 1.0
    step_info(f"Looking at villager center at ({px}, {look_y}, {pz})")
    try:
        player_look_at(float(px), look_y, float(pz))
    except Exception as e:
        step_fail("Looking at villager", str(e))
        return False
    flush()
    time.sleep(0.05)
    try:
        player_press_use(True)
    except Exception as e:
        step_fail("Press use (open trade)", str(e))
        return False
    flush()
    time.sleep(0.05)
    try:
        player_press_use(False)
    except Exception:
        pass
    flush()
    time.sleep(0.1)
    return True


def _is_merchant_screen_java():
    try:
        from java import JavaClass
        for mc_name in ("net.minecraft.client.Minecraft", "net.minecraft.class_310"):
            try:
                Minecraft = JavaClass(mc_name)
                mc = Minecraft.getInstance()
                if mc is None:
                    return False, ""
                screen = _get_current_screen_java(mc)
                if screen is None:
                    return False, ""
                cls_name = screen.getClass().getName()
                is_merchant = (
                    "MerchantScreen" in cls_name
                    or "merchant" in cls_name.lower()
                    or "class_492" in cls_name
                    or "Villager" in cls_name
                    or "villager" in cls_name.lower()
                )
                return is_merchant, cls_name
            except Exception:
                continue
        return False, ""
    except Exception as e:
        return False, str(e)


def wait_for_merchant_screen(timeout_sec=5.0):
    step_info("Waiting for trade screen...")
    try:
        initial_name = screen_name()
    except Exception:
        initial_name = None
    had_screen_at_start = bool(initial_name and str(initial_name).strip())
    start = time.time()
    last_log = 0.0
    while time.time() - start < timeout_sec:
        try:
            name = screen_name()
        except Exception:
            name = None
        elapsed = time.time() - start
        has_screen = bool(name and str(name).strip())
        if name and ("merchant" in name.lower() or "trade" in name.lower() or "villager" in name.lower()):
            step_ok("Trade screen open")
            return True
        is_merchant, cls_name = _is_merchant_screen_java()
        if is_merchant:
            step_ok("Trade screen open (Java check)")
            return True
        if not had_screen_at_start and elapsed >= 0.1 and has_screen:
            step_ok("Trade screen open (screen appeared after use)")
            return True
        if elapsed >= 0.2 and has_screen:
            step_ok("Trade screen open (assuming open screen is trade)")
            return True
        if elapsed - last_log >= 1.0:
            step_info(f"screen_name()={name!r}  Java class={cls_name or '(none)'}")
            last_log = elapsed
        if exit_requested:
            return False
        time.sleep(0.05)
    try:
        name = screen_name()
    except Exception:
        name = None
    _, cls_name = _is_merchant_screen_java()
    step_fail("Trade screen did not open", f"timeout (screen_name={name!r}, class={cls_name})")
    return False


def _get_current_screen_java(mc):
    try:
        screen = mc.screen
        if screen is not None and hasattr(screen, "getMenu"):
            return screen
    except Exception:
        pass
    try:
        screen = mc.getScreen()
        return screen
    except Exception:
        pass
    try:
        clazz = mc.getClass()
        methods = clazz.getDeclaredMethods()
        n = getattr(methods, "length", None) or getattr(methods, "size", lambda: 0)() or len(methods)
        for i in range(n):
            m = methods[i] if hasattr(methods, "__getitem__") else methods.get(i)
            if m is None or m.getParameterCount() != 0:
                continue
            rt = m.getReturnType()
            rname = (rt.getName() or "") if rt and hasattr(rt, "getName") else str(rt) if rt else ""
            if rname and "Screen" not in rname and "437" not in rname and "Gui" not in rname and "492" not in rname and "creen" not in rname.lower():
                continue
            try:
                m.setAccessible(True)
                screen = m.invoke(mc)
            except Exception:
                continue
            if screen is not None and hasattr(screen, "getMenu"):
                return screen
        for i in range(n):
            m = methods[i] if hasattr(methods, "__getitem__") else methods.get(i)
            if m is None or m.getParameterCount() != 0:
                continue
            try:
                m.setAccessible(True)
                screen = m.invoke(mc)
            except Exception:
                continue
            if screen is not None and hasattr(screen, "getMenu"):
                return screen
    except Exception:
        pass
    return None


def get_trade_offers_via_java():
    try:
        from java import JavaClass
        for mc_name in ("net.minecraft.client.Minecraft", "net.minecraft.class_310"):
            try:
                Minecraft = JavaClass(mc_name)
                break
            except Exception:
                continue
        else:
            step_info("Could not load Minecraft class")
            return []
        mc = Minecraft.getInstance()
        if mc is None:
            return []
        screen = _get_current_screen_java(mc)
        if screen is None:
            return []
        menu = screen.getMenu() if hasattr(screen, "getMenu") else None
        if menu is None:
            return []
        offers = None
        if hasattr(menu, "getOffers"):
            offers = menu.getOffers()
        elif hasattr(menu, "offers"):
            get_off = getattr(menu, "offers", None)
            offers = get_off() if callable(get_off) else get_off
        if offers is None:
            return []
        out = []
        size = offers.size()
        for i in range(size):
            offer = offers.get(i)
            if offer is None:
                continue
            result = offer.getResult() if hasattr(offer, "getResult") else None
            if result is not None and not result.isEmpty():
                out.append((i, result))
        return out
    except Exception as e:
        step_info(f"Java trade offers failed: {e}")
        return []


def _enchant_id_from_key(key):
    if key is None:
        return None
    try:
        if hasattr(key, "getKey"):
            rk = key.getKey()
            if rk is not None and hasattr(rk, "location"):
                return str(rk.location())
    except Exception:
        pass
    try:
        if hasattr(key, "value"):
            val = key.value()
            if val is not None and hasattr(val, "getKey"):
                rk = val.getKey()
                if rk is not None and hasattr(rk, "location"):
                    return str(rk.location())
    except Exception:
        pass
    s = str(key)
    m = re.search(r'/\s*(minecraft:[\w]+)\]', s)
    if m:
        return m.group(1)
    m = re.search(r'(minecraft:[\w]+)', s)
    if m:
        return m.group(1)
    return None


def get_enchants_from_item(item_handle):
    out = []
    try:
        from java import JavaClass
        for class_name in (
            "net.minecraft.core.component.DataComponents",
            "net.minecraft.component.DataComponentTypes",
        ):
            try:
                comp_type_class = JavaClass(class_name)
            except Exception:
                continue

            for comp_name in ("STORED_ENCHANTMENTS", "ENCHANTMENTS"):
                try:
                    comp_type = getattr(comp_type_class, comp_name, None)
                    if comp_type is None:
                        continue
                    comp = item_handle.get(comp_type)
                    if comp is None:
                        continue

                    entries = None
                    for method_name in ("entrySet", "getEnchantmentEntries", "object2IntEntrySet"):
                        try:
                            fn = getattr(comp, method_name, None)
                            if fn is not None:
                                entries = fn()
                                if entries is not None:
                                    break
                        except Exception:
                            continue

                    if entries is None:
                        continue

                    it = entries.iterator() if hasattr(entries, "iterator") else iter(entries)
                    while True:
                        try:
                            entry = it.next() if hasattr(it, "next") else next(it)
                        except (StopIteration, Exception):
                            break

                        key = entry.getKey() if hasattr(entry, "getKey") else entry
                        eid = _enchant_id_from_key(key)
                        if not eid:
                            continue

                        level = 1
                        for lv_method in ("getIntValue", "getValue"):
                            try:
                                fn = getattr(entry, lv_method, None)
                                if fn is not None:
                                    level = int(fn())
                                    break
                            except Exception:
                                continue
                        else:
                            try:
                                level = int(comp.getLevel(key))
                            except Exception:
                                pass

                        out.append((eid, level))

                    if out:
                        return out
                except Exception:
                    continue
            if out:
                break
    except Exception as e:
        step_info(f"get_enchants_from_item: {e}")
    return out


def item_has_enchantment(item_handle, want_enchant_id, min_level=None):
    for eid, lvl in get_enchants_from_item(item_handle):
        if want_enchant_id in eid or want_enchant_id.replace("minecraft:", "") in eid:
            if min_level is None or lvl >= min_level:
                return True
    return False


def check_trades_for_enchant(want_enchant_id, min_level=None):
    offers = get_trade_offers_via_java()
    if offers is None:
        return False, "could not get offers (Java)"
    if not offers:
        return False, "no trade offers"
    level_str = f" Lv>={min_level}" if min_level is not None else ""
    want_short = want_enchant_id.replace("minecraft:", "")
    for idx, result_item in offers:
        enchants = get_enchants_from_item(result_item)
        has_str = ", ".join(f"{e.replace('minecraft:','')} Lv{l}" for e, l in enchants) if enchants else "none"
        echo(f"  WANTS: {want_short}{level_str}  |  HAS: {has_str}")
        if item_has_enchantment(result_item, want_enchant_id, min_level):
            step_ok(f"MATCH found in trade #{idx}")
            return True, f"trade #{idx}"
    return False, "not in offers"


def close_trade_screen():
    step_info("Closing trade screen...")
    for mc_name in ("net.minecraft.client.Minecraft", "net.minecraft.class_310"):
        try:
            from java import JavaClass
            Minecraft = JavaClass(mc_name)
            mc = Minecraft.getInstance()
            if mc is not None:
                mc.setScreen(None)
                step_ok("Trade screen closed")
                return True
        except Exception as e:
            step_info(f"Close screen try {mc_name}: {e}")
            continue
    step_fail("Close screen", "Java setScreen(null) failed")
    return False


def _pos_xyz(position):
    if hasattr(position, "__getitem__") and len(position) >= 3:
        return float(position[0]), float(position[1]), float(position[2])
    if hasattr(position, "x") and hasattr(position, "y") and hasattr(position, "z"):
        return float(position.x), float(position.y), float(position.z)
    return None


def find_lectern_near(position, radius=3):
    p = _pos_xyz(position)
    if p is None:
        return None
    ox, oy, oz = int(p[0]), int(p[1]), int(p[2])
    candidates = sorted(
        [(abs(dx)+abs(dy)+abs(dz), ox+dx, oy+dy, oz+dz)
         for dy in range(-1, 2)
         for dx in range(-radius, radius+1)
         for dz in range(-radius, radius+1)]
    )
    for _, x, y, z in candidates:
        try:
            block = getblock(x, y, z)
            if block and "lectern" in block.lower():
                return (x, y, z)
        except Exception:
            continue
    return None


def find_best_axe_slot():
    priority = ["netherite", "diamond", "iron", "stone", "golden", "wooden"]
    try:
        inv = player_inventory()
    except Exception:
        return None
    best_slot = None
    best_rank = len(priority)
    for stack in (inv or []):
        slot = getattr(stack, "slot", None)
        item = str(getattr(stack, "item", None) or getattr(stack, "id", None) or "").lower()
        if slot is None or not (0 <= slot <= 8):
            continue
        if "axe" not in item:
            continue
        for rank, material in enumerate(priority):
            if material in item and rank < best_rank:
                best_rank = rank
                best_slot = slot
                break
    return best_slot


def break_lectern(pos):
    x, y, z = pos

    axe_slot = find_best_axe_slot()
    if axe_slot is None:
        step_info("No axe in hotbar, falling back to /setblock (lectern won't drop)")
        try:
            execute(f"/setblock {x} {y} {z} air")
            step_ok(f"Broke lectern at ({x}, {y}, {z}) via setblock")
            return True
        except Exception as e:
            step_fail("Break lectern", str(e))
            return False

    try:
        player_inventory_select_slot(axe_slot)
    except Exception as e:
        step_fail("Select axe slot", str(e))
        return False
    flush()
    time.sleep(0.05)

    try:
        player_look_at(x + 0.5, y + 0.5, z + 0.5)
    except Exception as e:
        step_fail("Look at lectern", str(e))
        return False
    flush()
    time.sleep(0.1)

    step_info(f"Breaking lectern at ({x},{y},{z}) with axe slot {axe_slot}...")
    try:
        player_press_attack(True)
        flush()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            time.sleep(0.1)
            try:
                block = getblock(x, y, z)
                if not block or "lectern" not in block.lower():
                    break
            except Exception:
                break
        player_press_attack(False)
        flush()
    except Exception as e:
        try:
            player_press_attack(False)
        except Exception:
            pass
        step_fail("Break lectern (attack)", str(e))
        return False

    try:
        block = getblock(x, y, z)
        if block and "lectern" in block.lower():
            step_fail("Break lectern", "block still there after 5s")
            return False
    except Exception:
        pass

    step_ok(f"Broke lectern at ({x},{y},{z})")
    return True


def _block_pos_xyz(position):
    p = _pos_xyz(position)
    if p is None:
        return None
    return int(p[0]), int(p[1]), int(p[2])


def _is_solid_place_target(x, y, z):
    try:
        at = getblock(x, y, z)
        below = getblock(x, y - 1, z)
    except Exception:
        return False
    at = (at or "").lower()
    below = (below or "").lower()
    if "air" in at or "replaceable" in at or "grass" in at or "flower" in at or "snow" in at:
        pass
    else:
        return False
    if not below or "air" in below or "water" in below or "lava" in below:
        return False
    return True


def pick_lectern_place_pos(lectern_pos, villager_position):
    vp = _block_pos_xyz(villager_position)
    if vp is None:
        return lectern_pos
    vx, vy, vz = vp
    x, y, z = lectern_pos
    candidates = [
        (x, y, z),
        (x + 1, y, z), (x - 1, y, z), (x, y, z + 1), (x, y, z - 1),
        (x + 1, y, z + 1), (x - 1, y, z + 1), (x + 1, y, z - 1), (x - 1, y, z - 1),
    ]
    for cx, cy, cz in candidates:
        if (cx, cy, cz) == (vx, vy, vz) or (cx, cy, cz) == (vx, vy + 1, vz):
            continue
        if not _is_solid_place_target(cx, cy, cz):
            continue
        if (cx, cy, cz) != lectern_pos:
            step_info(f"Placing lectern at ({cx},{cy},{cz}) (villager at {vp})")
        return (cx, cy, cz)
    step_info("No block free of villager; using original pos anyway")
    return lectern_pos


def find_lectern_slot_in_hotbar():
    try:
        inv = player_inventory()
    except Exception as e:
        step_fail("Get inventory", str(e))
        return None
    if not inv:
        step_fail("Get inventory", "empty list")
        return None
    for stack in inv:
        slot = getattr(stack, "slot", None)
        item = getattr(stack, "item", None) or getattr(stack, "id", None) or ""
        if slot is not None and 0 <= slot <= 8:
            if item and "lectern" in str(item).lower():
                step_ok(f"Lectern in hotbar slot {slot}")
                return slot
    step_fail("No lectern in hotbar", "put a lectern in hotbar 0-8")
    return None


def place_lectern_at(pos):
    slot = find_lectern_slot_in_hotbar()
    if slot is None:
        return False
    try:
        player_inventory_select_slot(slot)
    except Exception as e:
        step_fail("Select lectern slot", str(e))
        return False
    flush()
    time.sleep(0.1)
    x, y, z = pos
    try:
        player_look_at(x + 0.5, y, z + 0.5)
    except Exception:
        pass
    flush()
    time.sleep(0.05)
    try:
        player_press_use(True)
    except Exception as e:
        step_fail("Place lectern (use)", str(e))
        return False
    flush()
    time.sleep(0.05)
    try:
        player_press_use(False)
    except Exception:
        pass
    flush()
    step_ok("Placed lectern")
    return True


def wait_for_villager_relink(librarian=None, timeout=2.0):
    step_info("Waiting 2s for villager to claim lectern...")
    end = time.time() + timeout
    while time.time() < end:
        if exit_requested:
            return
        time.sleep(0.1)
    step_ok("Wait complete")


def run_list_mode():
    echo("=== List mode: reading current trade screen ===")
    echo("Open a librarian trade screen... (Press Escape to cancel)")
    if not wait_for_merchant_screen(timeout_sec=300):
        echo("Cancelled or timeout.")
        return
    offers = get_trade_offers_via_java()
    if not offers:
        echo("No offers found on this screen.")
        return
    echo(f"Found {len(offers)} trade(s):")
    for idx, result_item in offers:
        try:
            item_name = result_item.getItem().getDescriptionId().replace("item.minecraft.", "")
        except Exception:
            item_name = "?"
        enchants = get_enchants_from_item(result_item)
        if enchants:
            parts = [f"{eid.replace('minecraft:','')} Lv{lv}" for eid, lv in enchants]
            echo(f"  Trade {idx}: {item_name} -> {', '.join(parts)}")
        else:
            echo(f"  Trade {idx}: {item_name} (no enchants detected)")
    echo("Done.")


def main():
    global STEP, exit_requested
    exit_requested = False
    listener = threading.Thread(target=_exit_listener_thread_fn, daemon=True)
    listener.start()

    raw = sys.argv[1:]
    if len(raw) == 1 and " " in (raw[0] or ""):
        args = raw[0].strip().split()
    else:
        args = [a.strip() for a in raw if a is not None]
    if any(a == "--list" for a in args):
        run_list_mode()
        return

    want = " ".join(a for a in args if a and a != "--list").strip() or None
    want_enchant_id, want_min_level = normalize_enchant(want)
    if not want_enchant_id:
        echo("Usage: \\librarian_enchant_cycle ENCHANT_NAME [LEVEL]")
        echo("       \\librarian_enchant_cycle --list   (list enchants on open trade)")
        echo("Examples: \\librarian_enchant_cycle mending")
        echo("          \\librarian_enchant_cycle Sharpness 5   or   Sharpness V")
        return

    echo("=== Librarian Enchant Cycle Bot ===")
    echo(f"Target enchant: {want_enchant_id}" + (f" (level >= {want_min_level})" if want_min_level else ""))
    echo("Press Escape to stop.")
    STEP = 0

    attempt = 0
    cached_librarian = None
    cached_lectern_pos = None

    while True:
        if exit_requested:
            echo("Stopped by user (Escape).")
            return
        attempt += 1
        echo(f"--- Attempt {attempt} ---")

        if cached_librarian is None:
            cached_librarian = find_closest_librarian()
            if not cached_librarian:
                echo("Aborting: no librarian found.")
                return
        librarian = cached_librarian

        if not open_trade_with_villager(librarian):
            step_fail("Open trade", "could not interact")
            return
        flush()
        if not wait_for_merchant_screen():
            step_fail("Open trade", "screen did not open")
            return

        found, detail = check_trades_for_enchant(want_enchant_id, want_min_level)
        if found:
            msg = f"SUCCESS: Enchant '{want_enchant_id}'"
            if want_min_level is not None:
                msg += f" (level>={want_min_level})"
            msg += " is in the trade list. Done."
            echo(msg)
            return

        if not close_trade_screen():
            step_fail("Close trade", "could not close")
            return
        flush()

        if cached_lectern_pos is None:
            cached_lectern_pos = find_lectern_near(getattr(librarian, "position", None))
            if not cached_lectern_pos:
                step_fail("Find lectern", "no lectern near villager")
                return
        lectern_pos = cached_lectern_pos

        if not break_lectern(lectern_pos):
            return
        flush()

        place_pos = pick_lectern_place_pos(lectern_pos, getattr(librarian, "position", None))
        if place_pos is None:
            place_pos = lectern_pos
        if not place_lectern_at(place_pos):
            echo("Aborting: could not place lectern.")
            return
        cached_lectern_pos = place_pos
        flush()

        wait_for_villager_relink()
        if exit_requested:
            echo("Stopped by user (Escape).")
            return


if __name__ == "__main__":
    main()
