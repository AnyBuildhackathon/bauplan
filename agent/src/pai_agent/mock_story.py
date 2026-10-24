"""Deterministic demo. Same tools as the Claude loop, fixed choices.

run_mock builds v1 from the kickoff, run_review builds the next version from a review.
"""

from __future__ import annotations

import asyncio
import math

from pai_agent.context import Ctx, de
from pai_agent.env import pace_seconds
from pai_agent.meetings import fmt_number, short_date
from pai_agent.tools.registry import call_tool


async def _beat() -> None:
    delay = pace_seconds()
    if delay:
        await asyncio.sleep(delay)


async def _need(ctx: Ctx, name: str, args: dict) -> dict:
    result = await call_tool(ctx, name, args)
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or name)
    return result


async def _say(ctx: Ctx, state: str, say: str, chat: str | None = None) -> None:
    await _need(ctx, "mascot_say", {"state": state, "say": say})
    await ctx.chat("agent", chat or say)


def _numbers(metrics: dict) -> str:
    return (
        de(metrics["weight_g"], 1)
        + " g, Schub-Gewicht "
        + de(metrics["thrust_to_weight"], 2)
        + ", "
        + de(metrics["flight_time_min"], 1)
        + " min, "
        + de(metrics["price_eur"], 2)
        + " €"
    )


def _who(quote: dict) -> str:
    """'Ben um 20:06', or just 'Ben' when the transcript has no times."""

    return quote["speaker"] + (" um " + quote["time"] if quote.get("time") else "")


def _tip_speed(part: dict) -> float:
    """Idle blade-tip speed in m/s: KV times volts is rpm, times the propeller circumference."""

    return float(part["kv"]) * 3.8 * math.pi * 0.040 / 60.0


async def _build_tail(ctx: Ctx, meeting_id: str, label: str) -> dict:
    """Frame in FreeCAD, real frame mass, Blender, bill of materials, Jamie tasks, version."""

    await _beat()
    await ctx.step("cad", "running")
    arm = float(ctx.state.cad_params.get("arm_length_mm") or 0)
    if not arm:
        await _say(
            ctx,
            "erklaert",
            "Rahmen in FreeCAD. Erst mal kompakt.",
            "Jetzt der Rahmen in FreeCAD: 28 mm von der Mitte zur Motorwelle, 2 mm stark, Lochkreis 6,6 mm für die 1102er.",
        )
        tight = await call_tool(ctx, "cad_frame", {"arm_length_mm": 28, "thickness_mm": 2, "motor_spacing_mm": 6.6})
        if tight.get("ok") is False:
            await _say(ctx, "besorgt", "Zu eng. Die Propeller schlagen aneinander.", tight["error"] + " Ich nehme 36 mm, dann bleiben 11 mm Luft.")
        arm = 36.0
    cad = await _need(ctx, "cad_frame", {"arm_length_mm": arm, "thickness_mm": 2, "motor_spacing_mm": 6.6})
    await ctx.step("cad", "done")
    await _need(ctx, "ui_point_at", {"target": "frame", "label": "Rahmen " + de(cad["mass_g"], 1) + " g"})
    metrics = await _need(ctx, "physics_calc", {})
    await ctx.chat(
        "agent",
        "Der Rahmen wiegt laut "
        + ("FreeCAD " if cad["source"] == "freecad" else "CadQuery ")
        + de(cad["mass_g"], 1)
        + " g PLA. Mit den echten Teilen: "
        + _numbers(metrics)
        + ".",
    )

    await _beat()
    await ctx.step("render", "running")
    rendered = await _need(ctx, "blender_render", {})
    await ctx.step("render", "done")
    if rendered.get("status") == "offline":
        await _say(ctx, "ruhig", "Blender fehlt hier. Das STL reicht zum Drucken.")
    else:
        await _say(ctx, "erklaert", "Blender hat " + label + " im Studio gerendert.")

    await _beat()
    await ctx.step("stueckliste", "running")
    await _need(ctx, "bom_build", {})
    tasks = await _need(ctx, "jamie_create_tasks", {"meeting_id": meeting_id})
    version = await _need(ctx, "version_commit", {"meeting_id": meeting_id})
    await ctx.step("stueckliste", "done")
    version["tasks"] = tasks
    return version


async def run_mock(ctx: Ctx, meeting_id: str = "") -> None:
    await _beat()
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "Erst das Meeting. Sonst optimieren wir ins Blaue.")
    await _need(ctx, "jamie_templates", {})
    requirements = await _need(ctx, "jamie_requirements", {"meeting_id": meeting_id})
    kickoff_id = requirements["meeting_id"]
    await ctx.chat(
        "agent",
        str(len(requirements["requirements"]))
        + " Vorgaben aus „"
        + requirements["title"]
        + "“. Budget, Flugzeit und Gewicht stehen in der Vorlage Hardware-Anforderungen, jede mit dem Satz und wer ihn gesagt hat. Die Vorlagen für Kickoff und Review habe ich bei Jamie selbst angelegt.",
    )
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": requirements["title"]})
    motors = await _need(ctx, "jamie_search", {"query": "1102"})
    funfly = await _need(ctx, "jamie_search", {"query": "FunFly"})
    warned = any(meeting["quotes"] for meeting in funfly["meetings"])
    if motors["meetings"] and warned:
        await _say(
            ctx,
            "erklaert",
            "Letzte Woche flog der 22000KV sauber. Vor dem FunFly wurde gewarnt.",
            "Bei Jamie steht: Im Flugtest am 17.10. schwebte der 1102 mit 22000KV sauber. In der Werkstattnotiz vom 2.9. warnt Lea vor dem FunFly 4S an den 1102ern. Ich rechne es trotzdem einmal durch, sonst glaubt es keiner.",
        )
    else:
        await _say(
            ctx,
            "denkt",
            "Keine alten Notizen zu diesen Teilen. Ich rechne alles nach.",
            "Bei Jamie finde ich keine früheren Meetings zu den 1102ern oder zum FunFly. Dann rechne ich jedes Teil selbst nach.",
        )
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    await _say(ctx, "denkt", "Zehn Minuten klingen nach viel Akku. Das ist die Falle.")
    await _need(
        ctx,
        "parts_search",
        {"category": "motor", "query": "22000", "select_id": "betafpv-1102-22000kv", "reason": "Lief im Flugtest letzte Woche sauber, 46,3 g Schub pro Motor."},
    )
    await _need(
        ctx,
        "parts_search",
        {"category": "propeller", "query": "1635", "select_id": "gemfan-1635-3", "reason": "Auf diesem Propeller misst BetaFPV den Schub der 1102er."},
    )
    await _need(
        ctx,
        "parts_search",
        {
            "category": "battery",
            "query": "FunFly",
            "select_id": "tattu-funfly-4s-1300",
            "because": "flight_time",
            "reason": "1300 mAh sehen nach zehn Minuten aus. Das prüfe ich.",
        },
    )
    await _need(
        ctx,
        "parts_search",
        {
            "category": "flight_controller",
            "query": "AIO",
            "select_id": "betafpv-f4-1s-12a-aio-v3",
            "because": "weight",
            "reason": "Regler und vier ESCs auf einer Platine, 4,7 g.",
        },
    )
    await _need(
        ctx,
        "parts_search",
        {"category": "frame", "query": "Rahmen", "select_id": "printed-whoop-frame", "because": "printable", "reason": "Kommt aus eurem Drucker, als STL."},
    )
    first = await _need(ctx, "physics_calc", {})
    battery_g = float(ctx.state.selected["battery"]["mass_g"])
    await ctx.chat("agent", "Erster Wurf: " + _numbers(first) + ". Der Akku allein wiegt " + de(battery_g, 1) + " g. " + " ".join(first["warnings"]))

    await _beat()
    await ctx.step("simulation", "running")
    failed = await _need(ctx, "simulate_drone", {})
    await ctx.step("simulation", "failed")
    await _say(
        ctx,
        "besorgt",
        "Die Böe drückt sie auf den Boden. Der Akku ist der Klumpen.",
        ("Lea hatte recht: " if warned else "")
        + "Bei Schub-Gewicht "
        + de(failed["thrust_to_weight"], 2)
        + " bleibt keine Reserve für die Böe. Der Akku ist der Klumpen.",
    )
    await _need(ctx, "ui_point_at", {"target": "battery", "label": ctx.state.selected["battery"]["name"]})
    await _need(ctx, "ui_draw", {"kind": "halo", "target": "battery", "text": "zu schwer"})
    await _need(ctx, "ui_draw", {"kind": "arrow", "target": "battery", "text": de(battery_g, 1) + " g"})
    await _need(ctx, "ui_draw", {"kind": "circle", "target": "battery", "text": "4S an 1S-Motor"})
    await _need(
        ctx,
        "ui_draw",
        {"kind": "note", "target": "battery", "text": "Schub " + de(first["thrust_g"], 0) + " g, Masse " + de(first["weight_g"], 0) + " g"},
    )

    await _beat()
    await ctx.step("teile", "running")
    await _say(
        ctx,
        "erklaert",
        "Runter von 4S. Dieselben Motoren, anderer Akku.",
        "Ich tausche nur den Akku: Lava 1S 550, 14 g, 3,8 V. Die 1102er bleiben, ihr Datenblatt-Schub gilt für genau diese Spannung.",
    )
    await _need(
        ctx,
        "parts_search",
        {
            "category": "battery",
            "query": "Lava",
            "select_id": "betafpv-lava-1s-550",
            "because": "weight",
            "reason": "14 g statt 150 g, und 1S passt zu den Motoren.",
        },
    )
    second = await _need(ctx, "physics_calc", {})
    await ctx.step("teile", "done")
    await ctx.chat("agent", "Neu: " + _numbers(second) + ". Die Flugzeit ist eine Schätzung aus dem Datenblatt, kein Flugbuch.")

    await _beat()
    await ctx.step("simulation", "running")
    passed = await _need(ctx, "simulate_drone", {})
    if passed.get("result") != "pass":
        raise RuntimeError("Der zweite MuJoCo-Lauf sollte schweben: " + passed.get("summary", ""))
    await ctx.step("simulation", "done")
    await _say(ctx, "freut_sich", "Zweiter Lauf hält die Böe. Kapazität ist nicht gratis.")
    await _need(ctx, "ui_draw", {"kind": "halo", "target": "battery", "text": "passt"})

    version = await _build_tail(ctx, kickoff_id, "v1")
    await _need(ctx, "ui_point_at", {"target": "timeline", "label": "v1 hängt am Kickoff"})
    await _say(
        ctx,
        "freut_sich",
        "v1 steht. Notiz, Tags und Aufgaben liegen bei Jamie.",
        "Version 1 hängt am Kickoff: "
        + version["detail"].split(" · ", 1)[-1]
        + ". Bei Jamie liegen eine Notiz, die Tags drohne und drohne-v1 und "
        + str(version["tasks"]["task_count"])
        + " Bestellaufgaben für Lea und Ben. Preise sind Stichproben, vor dem Bestellen prüfen.",
    )
    ctx.state.finished = True


async def run_review(ctx: Ctx, meeting_id: str) -> None:
    ctx.state.finished = False
    await _beat()
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "Review ist vorbei. Ich lese, was sich geändert hat.")
    review = await _need(ctx, "jamie_meeting", {"meeting_id": meeting_id})
    lines = []
    for change in review["changes"]:
        lines.append(_who(change["quote"]) + ": „" + change["quote"]["text"] + "“")
    for complaint in review["complaints"]:
        lines.append(_who(complaint["quote"]) + ": „" + complaint["quote"]["text"] + "“")
    if lines:
        await ctx.chat("agent", "Aus „" + review["title"] + "“:\n\n" + "\n\n".join(lines))

    accept: list[str] = [change["id"] for change in review["changes"]]
    for conflict in review["conflicts"]:
        old, new = conflict["old"], conflict["new"]
        await _need(ctx, "mascot_say", {"state": "denkt", "say": "Das widerspricht dem Kickoff. Ich frag lieber."})
        new_value = fmt_number(float(new["limit"])) + " " + conflict["unit"]
        old_value = fmt_number(float(old["limit"])) + " " + conflict["unit"]
        answer = await _need(
            ctx,
            "ask_user",
            {
                "question": old["meeting_title"]
                + ", "
                + _who(old)
                + ": „"
                + old["source_quote"]
                + "“\n"
                + new["meeting_title"]
                + ", "
                + _who(new)
                + ": „"
                + new["source_quote"]
                + "“\nBaue ich auf "
                + new_value
                + "?",
                "options": [
                    {"id": "new", "label": new_value + " (" + new["meeting_title"] + ")"},
                    {"id": "old", "label": old_value + " (" + old["meeting_title"] + ")"},
                ],
                "default_id": "new",
            },
        )
        if answer["answer_id"] == "old":
            accept.remove(conflict["id"])
    if accept:
        await _need(ctx, "requirements_accept", {"meeting_id": meeting_id, "ids": accept})
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": review["title"]})

    complaint = next((c for c in review["complaints"] if c["category"] == "motor"), None)
    refers = (complaint or {}).get("refers_to")
    if complaint and refers:
        await _say(
            ctx,
            "erklaert",
            "„Der Motor von letzter Woche“ ist der 22000KV aus dem Flugtest.",
            "„Der Motor von letzter Woche“: Bei Jamie steht im Flugtest vom "
            + short_date(refers["date"])
            + " "
            + _who(refers["quote"])
            + ": „"
            + refers["quote"]["text"]
            + "“ Das ist "
            + refers["name"]
            + ", genau der Motor in v1.",
        )
    elif complaint and complaint["last_week"]:
        await _say(
            ctx,
            "denkt",
            "Letzte Woche finde ich kein Meeting dazu. Gemeint ist wohl der Motor aus v1.",
            "Ein Meeting von letzter Woche mit einem Motor finde ich bei Jamie nicht. Ich nehme an, gemeint ist der Motor aus v1: "
            + ctx.state.selected["motor"]["name"]
            + ".",
        )
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    if complaint:
        old_motor = ctx.state.selected["motor"]
        await _need(ctx, "parts_search", {"category": "motor", "query": "1102"})
        from pai_agent.tools.parts import catalog

        quiet = next(p for p in catalog()["parts"] if p["id"] == "betafpv-1102-18000kv")
        await _need(
            ctx,
            "parts_search",
            {
                "category": "motor",
                "query": "18000",
                "select_id": quiet["id"],
                "because": "complaint",
                "reason": "Weniger Drehzahl: Blattspitze "
                + de(_tip_speed(quiet), 0)
                + " statt "
                + de(_tip_speed(old_motor), 0)
                + " m/s, also leiser, und 2,11 statt 1,90 g/W.",
            },
        )
        await _need(ctx, "ui_point_at", {"target": "motor_front_left", "label": "18000KV, leiser"})
    target = next((r for r in ctx.state.requirements if r["id"] == "flight_time"), None)
    if target and float(target.get("min", 10)) > 12:
        await _need(ctx, "parts_search", {"category": "battery", "query": ""})
        await _say(
            ctx,
            "denkt",
            "Mehr Flugzeit heißt mehr Akku. Aber nicht der FunFly.",
            "Für " + de(float(target["min"]), 0) + " Minuten brauche ich mehr Kapazität. Der FunFly hätte sie, aber Jamie erinnert an Leas Warnung. Ich bleibe bei 1S und nehme 1100 mAh.",
        )
        await _need(
            ctx,
            "parts_search",
            {
                "category": "battery",
                "query": "1100",
                "select_id": "lihv-1s-1100",
                "because": "flight_time",
                "reason": "1100 mAh für " + de(float(target["min"]), 0) + " Minuten, 26 g, bleibt bei 1S.",
            },
        )
    metrics = await _need(ctx, "physics_calc", {})
    await ctx.step("teile", "done")
    await ctx.chat("agent", "Gerechnet: " + _numbers(metrics) + ".")

    await _beat()
    await ctx.step("simulation", "running")
    run = await _need(ctx, "simulate_drone", {})
    await ctx.step("simulation", "done" if run["result"] == "pass" else "failed")
    if run["result"] == "pass":
        await _say(ctx, "freut_sich", "Leiser, länger in der Luft, und sie hält die Böe immer noch.")
    else:
        await _say(ctx, "besorgt", "Das hält die Böe nicht. Ich schaue noch einmal auf die Teile.")

    version = await _build_tail(ctx, meeting_id, "v" + str(len(ctx.state.versions) + 1))
    changes = [
        item
        for item in version["diff"]
        if item["key"] in {"weight_g", "flight_time_min", "price_eur"}
    ]
    digits = {"weight_g": 1, "flight_time_min": 1, "price_eur": 2}
    parts = ", ".join(
        item["label"] + " " + de(item["before"], digits[item["key"]]) + " → " + de(item["after"], digits[item["key"]]) + " " + item["unit"]
        for item in changes
    )
    await _need(ctx, "ui_point_at", {"target": "metrics", "label": "v" + str(version["version"])})
    await _say(
        ctx,
        "freut_sich",
        "v" + str(version["version"]) + " steht. Die Differenz liegt als Notiz bei Jamie.",
        "Version "
        + str(version["version"])
        + " hängt an „"
        + review["title"]
        + "“: "
        + parts
        + ". Die Differenz steht als Notiz im Meeting, "
        + str(version["tasks"]["new"])
        + " neue Bestellaufgaben sind angelegt, "
        + str(version["tasks"]["closed"])
        + " alte geschlossen.",
    )
    ctx.state.finished = True


async def run_mock_followup(ctx: Ctx) -> None:
    if not ctx.state.finished:
        await _say(
            ctx,
            "besorgt",
            "Der letzte Lauf ist stehen geblieben. Einmal zurücksetzen.",
            "Setz die Sitzung zurück und schick den Satz noch einmal. Ich baue nicht auf einem halben Stand weiter.",
        )
        return
    await _say(
        ctx,
        "ruhig",
        "Die Version steht. Das nächste Review bei Jamie baut die nächste.",
        "Die Version steht. Sobald das nächste Review bei Jamie endet, baue ich neu und schreibe die Differenz zurück.",
    )
