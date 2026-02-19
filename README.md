# Librarian Enchant Cycle Bot
A Minescript bot for Minecraft 1.21.11 that automatically cycles a librarian villager's trades until it offers a specific enchanted book.

---

## Requirements

- [Minescript](https://minescript.net/) installed
- Minecraft 1.21.11 (Java Edition)
- A librarian villager set up near you
- A lectern placed next to the villager
- At least two **lectern** in your hotbar (slots 1–9) 
- An **axe** in your hotbar to break the lectern (netherite preferred, but any axe works)

---

## Setup

> **Important:** It is strongly recommended to box your librarian in a small enclosed space (e.g. a corner with walls) with the lectern placed right next to them. The bot is **not tested for multiple villagers in close proximity** — if other villagers are nearby it may target the wrong one. Isolating your librarian removes this risk entirely.

Place the lectern directly adjacent to the villager. The bot searches for a lectern within a **3 block radius** of the villager's position, so keep it close.

---

## How It Works

1. The bot opens the villager's trade menu
2. Checks the enchanted book trade for your requested enchant
3. If it doesn't match, it closes the menu, **breaks the lectern** with the best axe in your hotbar, and **places a new one** from your hotbar
4. Waits 2 seconds for the villager to claim the lectern and reset their trades
5. Repeats until the enchant is found

The lectern is destroyed and replaced each cycle — this is intentional and is how trade cycling works in vanilla Minecraft. Make sure you have enough lecterns in your hotbar to sustain the process (they'll drop and you can pick them back up, as the bot breaks them with an axe rather than deleting them).

---

## Axe Behaviour

The bot will automatically find the **best axe in your hotbar** to break the lectern, prioritising by material in this order:

**Netherite → Diamond → Iron → Stone → Golden → Wooden**

If no axe is found in your hotbar (slots 1–9), it falls back to forcibly removing the block without a drop — so make sure an axe is hotbarred.

---

## Usage

Run via the Minescript chat command:

```
\librarian_enchant_cycle <enchant_name>
\librarian_enchant_cycle <enchant_name> <level>
```

### Examples

```
\librarian_enchant_cycle mending
\librarian_enchant_cycle sharpness 5
\librarian_enchant_cycle unbreaking 3
\librarian_enchant_cycle protection IV
```

Levels can be written as **numbers** (`5`) or **Roman numerals** (`V`).

Press **Escape** at any time to stop the bot.

---

## Villager Search Range

| Thing          | Search Range         |
|----------------|----------------------|
| Villager       | 64 blocks            |
| Lectern        | 3 blocks from villager |

---

## Troubleshooting

- **"No villagers found"** — Stand closer to your librarian (within 64 blocks)
- **"No lectern in hotbar"** — Put a lectern in one of your hotbar slots (1–9)
- **"No lectern near villager"** — Make sure the lectern is within 3 blocks of the villager
- **Bot targets wrong villager** — Box your librarian off away from other villagers

---

## Version Support

Tested on **Minecraft 1.21.11**. I'll update the script for future versions if needed, though I don't expect it to require many changes.

---

## Credits

*AI was partially used in the development of this script, however the majority of the work, testing, debugging are my own.*
