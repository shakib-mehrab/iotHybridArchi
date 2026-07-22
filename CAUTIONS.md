Short answer: network.sh down destroys your data. Stopping Docker does not. They are completely different operations, and the confusion between them is exactly what bit you.

The three actions, ranked by how destructive they are

1. docker stop / Docker Desktop quit / PC reboot → SAFE. Data survives.

Fabric stores the ledger (blocks + world state in CouchDB) in Docker volumes. A volume is disk storage that lives outside the container. When you stop a container, the volume stays on disk. Start it again → the peer reattaches to the same volume → all your devices are still there.

So: you can shut down your PC every night, quit Docker, come back tomorrow, docker start the containers (or docker compose start), and your 4 devices are still registered. The network being "down" in this sense loses nothing.

2. network.sh down → DESTRUCTIVE. This is what wiped you.

This is not "stop." Look at what test-network's down actually does — it runs docker compose down --volumes and deletes the crypto material and channel artifacts. The --volumes flag is the killer: it deletes the volumes, which is where your ledger lives. So:

- All registered devices → gone
- All stored CID history → gone
- The channel itself → gone (you must createChannel again)
- Chaincode lifecycle → reset (you must deployCC again)

That is precisely the sequence that produced your "device not founeset, not a power-off.

3. deployCC again (without down) → keeps your data, but re-runs ch

Re-deploying chaincode on an existing channel does not wipe the woive a chaincode upgrade. It bumps the sequence number. So upgrading chaincode alone is safe for your device data. (What actually reset your version label to 1.0/seq1 was the full down + fresh deployCC, not an upgrade.)

So how is data "stored until next update, even if the network is down"?

Through the Docker volumes, as long as you stop rather than tear down:

┌────────────────────────────────────┬──────────────────┬───────────────────┬─────────────────────────┐
│               You do               │ Devices survive? │ Channel ves?   │
├────────────────────────────────────┼──────────────────┼───────────────────┼─────────────────────────┤
│ docker stop / quit Docker / reboot │ ✅ yes           │ ✅ yes         │
├────────────────────────────────────┼──────────────────┼───────────────────┼─────────────────────────┤
│ docker compose start (bring back)  │ ✅ yes           │ ✅ yes         │
├────────────────────────────────────┼──────────────────┼───────────────────┼─────────────────────────┤
│ network.sh down                    │ ❌ wiped         │ ❌ wiped       │
├────────────────────────────────────┼──────────────────┼───────────────────┼─────────────────────────┤
│ deployCC (upgrade, no down)        │ ✅ yes           │ ✅ yes  a kept │
└────────────────────────────────────┴──────────────────┴───────────────────┴─────────────────────────┘

Practical rules for you going forward

- To pause/shut down safely: don't use network.sh down. Just quit Docker Desktop, or docker stop $(docker ps -q). To resume: start Docker / docker start the
Fabric containers. No re-registration needed.
- After any real network.sh down: you must redo channel + chaincode + run register_devices.py (that's what this script is for).
- RAM note (per your CLAUDE.md): keeping the 5 Fabric containers so RAM — they're not running. So there's no memory cost to leavingthem in place between sessions instead of tearing down.

One caveat worth knowing: if you ever do need a clean shutdown of just the containers but want to be certain volumes stay, avoid any command with --volumes, -v,
or prune. Those are the only things that delete the on-disk ledger