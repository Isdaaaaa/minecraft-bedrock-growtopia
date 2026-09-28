# 🌱 Terravia — Growtopia-Like Minecraft Bedrock Server

A Growtopia-inspired game server built on **Minecraft Bedrock 1.26.51+** using **[Endstone](https://endstone.dev)**, featuring dynamic player-owned worlds, spatial shard architecture, per-world isolation, and sandbox gameplay.

---

## 🎮 Concept

Terravia recreates the Growtopia experience inside Minecraft Bedrock:

| Growtopia Feature | Terravia Implementation |
|---|---|
| Type a world name to enter/create it | `/gw <WORLDNAME>` — join or create in one command |
| Player-owned worlds | Each world has an owner, lock level, and access list |
| World Lock / Big Lock | 3-tier lock system enforced server-side |
| START world / Hub | Dedicated `terravia:hub` dimension — all players spawn here |
| World isolation (chat, tab list) | Per-world chat routing + tab list filtering |
| Sandbox building | 256×256×256 block space per world, Y-61 to Y194 |

---

## 🏗️ Architecture

### World Slot System

Each player world occupies a **4,096×4,096 block slot** in a shard dimension:

```
Slot layout (top-down):
┌─────────────────────────────────┐  4096 blocks
│   ~1920 block void buffer       │
│   ┌───────────────────────┐     │
│   │  256×256 playable     │     │  World space per player
│   │  area (your world)    │     │
│   └───────────────────────┘     │
│   ~1920 block void buffer       │
└─────────────────────────────────┘

World vertical space:
  Y 320   Sky (open, no ceiling — looks natural)
  Y 195+  Air (block placement blocked above Y194)
  Y 194   ← Build cap (256 blocks above bedrock floor)
  Y 0     Grass surface ← ground level
  Y -1    Dirt (4 layers)
  Y -5    Stone
  Y -20   Deepslate
  Y -62   Bedrock floor (3 layers)
  Y -64   Bottom of world
```

### Shard Dimensions

- **`terravia:hub`** — dedicated hub dimension (tutorial/lobby)
- **`minecraft:overworld`** — shard 0
- **`terravia:shard_1`** through **`terravia:shard_9`** — overflow shards

All 10 shards are **pre-defined at server startup** (no restarts needed when shards fill up). Each shard holds **~23.8 million world slots**. Total capacity: **~238 million worlds**.

### Isolation Layers

| Feature | How |
|---|---|
| Visual | 1,920-block void gap between worlds (beyond any render distance) |
| Chunk restriction | Server refuses to send chunks from other world slots |
| Chat | `PlayerChatEvent` cancelled → re-sent to same-world players only |
| Tab list | `hide_player()` called for all players not in your world |
| Movement | `PlayerMoveEvent` clamps player to their world's 256×256 boundary |
| Block placement | Cancelled if outside 256×256 boundary OR above Y194 / in bedrock |

---

## 📁 Project Structure

```
terravia/
├── behavior_pack/
│   ├── manifest.json
│   └── dimensions/
│       ├── hub.json            ← terravia:hub (lobby dimension)
│       ├── shard_1.json        ← terravia:shard_1
│       └── ... (shard_2 through shard_9)
│
└── plugin/
    ├── plugin.toml             ← Commands, permissions
    └── src/
        ├── __init__.py         ← Plugin entry point, event wiring
        ├── models.py           ← WorldSlot math, GrowWorld dataclass, constants
        ├── database.py         ← SQLite: worlds, slots, access, bans, sessions
        ├── shard_manager.py    ← Spiral slot allocator across shards
        ├── world_manager.py    ← Create/join/leave, boundaries, chunk restriction
        ├── world_template.py   ← Block layer generator (async, 4096 blocks/tick)
        ├── chat_manager.py     ← Per-world chat isolation
        ├── tablist_manager.py  ← Per-world tab list filtering
        └── commands.py         ← /gw and /gwadmin handlers
```

---

## ⌨️ Commands

### Player Commands
```
/gw <WORLDNAME>    Enter a world (creates it if it doesn't exist)
/gw leave          Return to the Hub
/gw info [name]    Show world details (owner, lock, shard, slot)
/gw lock           Cycle: Unlocked → World Lock → Big Lock → Unlocked
/gw add <player>   Grant build access to a player (owner only)
/gw remove <player>Revoke build access (owner only)
/gw kick <player>  Kick a player from your world (owner only)
/gw ban <player>   Ban a player from your world (owner only)
/gw unban <player> Unban a player from your world (owner only)
```

### Admin Commands
```
/gwadmin shards    Show fill level of all 10 dimension shards
/gwadmin tp <name> Teleport to any world (bypasses lock/ban)
```

---

## 🚀 Getting Started

### Prerequisites
- [Endstone](https://endstone.dev) v0.11.12+ (Minecraft Bedrock 1.26.51)
- Python 3.11+

### Installation

```bash
# Install Endstone
pip install endstone

# Clone this repo
git clone https://github.com/Isdaaaaa/minecraft-bedrock-growtopia.git
cd minecraft-bedrock-growtopia

# Copy the behavior pack to your BDS behavior_packs folder
cp -r behavior_pack/ path/to/bds/behavior_packs/terravia/

# Copy the plugin to your Endstone plugins folder
cp -r plugin/ path/to/endstone/plugins/terravia/

# Start the server
endstone
```

---

## 📄 License

MIT
