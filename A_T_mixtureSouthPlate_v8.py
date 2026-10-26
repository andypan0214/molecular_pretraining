"""Opentrons Flex: A1-A8 x T1-T12 in two NEST 96 deep-well plates.

V8: 95 uL A + 45 uL T/base premix per final well, 3 x 20 uL final mix.
    DCM tip pre-wetting (C2 A1) and a 25 uL air gap on every A and T transfer.
    Simplified 3-colour liquid visualization; DCM reservoir validation counts all
    eight nozzles.

C2: NEST 12-well reservoir; ONLY well A1 is used (5,000 uL DCM, manually preloaded)
    for tip pre-wetting. One pre-wet draws 8 nozzles x 200 uL = 1,600 uL from A1.
C3: reaction plate and A source. A1..H1 initially have 12 * volume_A each
    (12 * 95 = 1140 uL ideal). Columns 2..12 initially empty. Each row is a distinct A.
D3: T + Base premix source (96 deep well plate). Each column holds one premix
    in all eight wells; 45 uL is taken from each well.

Stage 1: Keep one set of eight tips for 11 A distributions (C3 col 1 -> 2..12).
         Tips are pre-wet ONCE with DCM right after pickup. Each A transfer:
         aspirate 95 uL A, withdraw above liquid, aspirate 25 uL air,
         dispense 120 uL (95 uL A + air gap) into the destination.
Stage 2: For each premix column, new eight tips, pre-wet with DCM (C2 A1), then
         aspirate 45 uL T+Base, withdraw, 25 uL air gap, dispense 70 uL (45 uL + air)
         into C3, then 3x20 uL mix in that destination column; discard tips.

Tips are never returned to C2 after contacting reagent.

FINAL per C3 well: 95 uL A + 45 uL T+Base = 140 uL.

Idealized volume bookkeeping only: zero dead volume, retention, or evaporation.
Set T_source_volume above volume_T to allow for D3 dead volume.
Do not execute with chemical reagents until simulation, liquid-only deck
verification, solvent/consumable compatibility confirmation, and a validated
laboratory SOP are complete.
"""
from opentrons import protocol_api

metadata = {
    "protocolName": "A x (T+Base) two deep-well plates (V8)",
    "author": "OpentronsAI / Xu Lab review",
    "description": "C3 A reaction plate (95 uL A), D3 T+Base premix source (45 uL T); DCM tip pre-wet, 25 uL air gaps, 3x mix after each addition.",
    "source": "OpentronsAI",
}
requirements = {"robotType": "Flex", "apiLevel": "2.28"}

ROWS = 8
COLS = 12
# Change BOTH rack definitions to 1000 uL if that is what is physically loaded.
TIP_RACK_LOAD_NAME = "opentrons_flex_96_tiprack_200ul"

# DCM pre-wetting and air gap settings (fixed by method)
N_NOZZLES = 8                # Flex 8-channel: all nozzles draw from C2 A1 simultaneously
DCM_VOLUME_LOADED = 5000.0   # uL manually preloaded in C2 A1
PREWET_VOLUME = 200.0        # uL DCM per nozzle, aspirate then dispense back to C2 A1
N_PREWETS = 1 + COLS         # 1 for Stage 1 + 12 for Stage 2 = 13
AIR_GAP_VOLUME = 25.0        # uL air after every A / T+Base aspiration
AIR_GAP_HEIGHT = 20.0        # mm above the well top for the air-gap aspiration (tips clear of liquid)
PREWET_ASP_HEIGHT = 2.0      # mm above C2 A1 well bottom for pre-wetting
PREWET_DISP_HEIGHT = 2.0     # mm above C2 A1 well bottom for pre-wet dispense back

# Liquid visualization colours (one colour per group; each reagent keeps its own definition)
A_COLOR = "#83A8BF"          # muted blue  - A1-A8
T_COLOR = "#89A99B"          # muted green - T1-T12 + Base
DCM_COLOR = "#B0B0B0"        # neutral gray - DCM


def add_parameters(parameters: protocol_api.ParameterContext):
    parameters.add_float(
        variable_name="volume_A", display_name="A volume per well",
        description="uL of A per final C3 well; column 1 initially needs 12x this.",
        default=95.0, minimum=5.0, maximum=160.0, unit="uL",
    )
    parameters.add_float(
        variable_name="volume_T", display_name="T+Base volume per well",
        description="uL of T+Base premix added to each C3 well from D3.",
        default=45.0, minimum=5.0, maximum=200.0, unit="uL",
    )
    parameters.add_float(
        variable_name="T_source_volume", display_name="T+Base volume loaded in D3",
        description="uL loaded per D3 well (must be >= T+Base volume per well).",
        default=45.0, minimum=5.0, maximum=2000.0, unit="uL",
    )
    parameters.add_bool(
        variable_name="mix_enabled", display_name="Mix after premix dispense",
        description="When on, mix each C3 column right after T+Base addition.",
        default=True,
    )
    parameters.add_int(
        variable_name="mix_reps", display_name="Destination mix repetitions",
        description="Aspirate/dispense cycles after dosing.",
        default=3, minimum=1, maximum=20,
    )
    parameters.add_float(
        variable_name="mix_volume", display_name="Destination mix volume",
        description="uL per mix cycle (not additional reagent).",
        default=20.0, minimum=5.0, maximum=200.0, unit="uL",
    )
    parameters.add_float(
        variable_name="A_asp_height", display_name="A source aspiration height",
        description="mm above C3 well bottom; verify at high and low liquid levels.",
        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="T_asp_height", display_name="Premix aspiration height",
        description="mm from D3 source well bottom; verify using liquid-only tests.",
        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_str(
        variable_name="stage1_dispense_ref", display_name="A dispense reference",
        description="Dispense either below well rim or above well bottom.",
        choices=[
            {"display_name": "Below well top", "value": "top"},
            {"display_name": "Above well bottom", "value": "bottom"},
        ],
        default="top",
    )
    parameters.add_float(
        variable_name="stage1_dispense_offset", display_name="A dispense offset",
        description="mm below the top OR above the bottom, per reference selected.",
        default=2.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="T_disp_height", display_name="Premix dispense height",
        description="mm above C3 destination well bottom when adding T+Base.",
        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="mix_height", display_name="Destination mixing height",
        description="mm above C3 well bottom for the pipette mixing operation.",
        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="asp_flow", display_name="Aspirate flow rate",
        description="uL/s; not validated for A/T liquids.",
        default=100.0, minimum=1.0, maximum=716.0, unit="uL/s",
    )
    parameters.add_float(
        variable_name="disp_flow", display_name="Dispense flow rate",
        description="uL/s; not validated for A/T liquids.",
        default=100.0, minimum=1.0, maximum=716.0, unit="uL/s",
    )
    parameters.add_float(
        variable_name="post_dispense_delay", display_name="Wait after T dispense",
        description="seconds before destination mixing.",
        default=1.0, minimum=0.0, maximum=10.0, unit="s",
    )


def run(protocol: protocol_api.ProtocolContext):
    p = protocol.params
    volume_A = p.volume_A
    volume_T = p.volume_T
    T_source_volume = p.T_source_volume
    initial_A = COLS * volume_A
    final_reaction = volume_A + volume_T

    tiprack_B3 = protocol.load_labware(TIP_RACK_LOAD_NAME, "B3")
    tiprack_B2 = protocol.load_labware(TIP_RACK_LOAD_NAME, "B2")
    dcm_reservoir = protocol.load_labware(
        "nest_12_reservoir_15ml", "C2", label="DCM pre-wet reservoir (A1 only)"
    )
    plate_C3 = protocol.load_labware(
        "nest_96_wellplate_2ml_deep", "C3", label="A1-A8 source and reaction"
    )
    plate_D3 = protocol.load_labware(
        "nest_96_wellplate_2ml_deep", "D3", label="T1-T12 + Base premix source"
    )
    protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument(
        "flex_8channel_1000", "right", tip_racks=[tiprack_B3, tiprack_B2]
    )
    # Flex 8-channel in default ALL layout: position commands at the top (A) well
    # of a column, and all eight nozzles move in parallel.
    C3_columns = [col[0] for col in plate_C3.columns()]
    D3_columns = [col[0] for col in plate_D3.columns()]
    if len(C3_columns) != COLS or len(D3_columns) != COLS:
        raise ValueError("Expected two 12-column 96-well plates.")

    # DCM pre-wet source: C2 A1 is the ONLY reservoir channel used.
    dcm_well = dcm_reservoir["A1"]

    # ---- Validate before any liquid handling ----
    c3_well = plate_C3["A1"]
    d3_well = plate_D3["A1"]
    tip_capacity = tiprack_B3["A1"].max_volume
    usable_capacity = min(pipette.max_volume, tip_capacity)
    min_volume = pipette.min_volume

    if initial_A > c3_well.max_volume:
        raise ValueError(f"12 x A = {initial_A} uL exceeds C3 source capacity.")
    if final_reaction > c3_well.max_volume:
        raise ValueError(f"A + T = {final_reaction} uL exceeds C3 well capacity.")
    if T_source_volume < volume_T:
        raise ValueError(
            f"D3 loaded volume ({T_source_volume} uL) is less than the "
            f"{volume_T} uL to be transferred."
        )
    if T_source_volume > d3_well.max_volume:
        raise ValueError("T source volume exceeds a D3 well's maximum volume.")
    for label, amount in (("volume_A", volume_A), ("volume_T", volume_T)):
        if not min_volume <= amount <= usable_capacity:
            raise ValueError(
                f"{label}={amount} uL outside pipette/tip range "
                f"{min_volume}-{usable_capacity} uL."
            )
    # Tip capacity checks including the 25 uL air gap (liquid + air must fit in the tip).
    for label, amount in (("volume_A", volume_A), ("volume_T", volume_T)):
        if amount + AIR_GAP_VOLUME > usable_capacity:
            raise ValueError(
                f"{label} {amount} uL + {AIR_GAP_VOLUME} uL air gap exceeds the "
                f"{usable_capacity} uL tip capacity."
            )
    if PREWET_VOLUME > usable_capacity:
        raise ValueError(f"Pre-wet volume {PREWET_VOLUME} uL exceeds tip capacity {usable_capacity} uL.")

    # DCM reservoir validation: all eight nozzles draw from C2 A1 at once.
    prewet_volume_per_operation = N_NOZZLES * PREWET_VOLUME            # 1,600 uL
    total_dcm_cycled = N_PREWETS * prewet_volume_per_operation          # 20,800 uL cycled
    dcm_well_capacity = dcm_well.max_volume                             # 15,000 uL
    if DCM_VOLUME_LOADED > dcm_well_capacity:
        raise ValueError(
            f"DCM loaded ({DCM_VOLUME_LOADED} uL) exceeds C2 A1 capacity "
            f"({dcm_well_capacity} uL)."
        )
    if prewet_volume_per_operation > DCM_VOLUME_LOADED:
        raise ValueError(
            f"One pre-wet withdraws {N_NOZZLES} x {PREWET_VOLUME} = "
            f"{prewet_volume_per_operation} uL, which exceeds the "
            f"{DCM_VOLUME_LOADED} uL DCM loaded in C2 A1."
        )
    # Each pre-wet dispenses the 1,600 uL back into A1, so the well is restored after every
    # operation; the real DCM loss is evaporation and tip wetting, which is not simulated.
    if p.mix_enabled and not min_volume <= p.mix_volume <= min(final_reaction, usable_capacity):
        raise ValueError("mix_volume outside pipette/tip range or exceeds final reaction volume.")
    for label, value, depth in (
        ("A_asp_height", p.A_asp_height, c3_well.depth),
        ("T_asp_height", p.T_asp_height, d3_well.depth),
        ("stage1_dispense_offset", p.stage1_dispense_offset, c3_well.depth),
        ("T_disp_height", p.T_disp_height, c3_well.depth),
        ("mix_height", p.mix_height, c3_well.depth),
    ):
        if not 0 < value < depth:
            raise ValueError(f"{label} must be between 0 and its well depth ({depth} mm).")
    tips_needed = (1 + COLS) * ROWS  # 1 x 8 for A and 12 x 8 for T = 104 tips
    tips_available = len(tiprack_B3.wells()) + len(tiprack_B2.wells())
    if tips_needed > tips_available:
        raise ValueError(f"Need {tips_needed} tips; only {tips_available} loaded.")

    protocol.comment(
        "LIQUID-ONLY PROTOTYPE: verify solvent compatibility, pipette/tip "
        "integrity, actual volumes, and safe lab conditions before chemistry."
    )
    protocol.comment(
        f"Target per C3 well: {volume_A} uL A + {volume_T} uL T+Base = "
        f"{final_reaction} uL. C3 column 1 initially {initial_A} uL per well; "
        f"D3 loaded with {T_source_volume} uL per well. Mixing: "
        f"{'ON' if p.mix_enabled else 'OFF'} "
        f"({p.mix_reps}x{p.mix_volume} uL). Tips: {tips_needed}. "
        f"DCM pre-wet: {PREWET_VOLUME} uL x {N_NOZZLES} nozzles = "
        f"{prewet_volume_per_operation} uL per operation, {N_PREWETS} operations "
        f"from C2 A1 (loaded {DCM_VOLUME_LOADED} uL); "
        f"air gap {AIR_GAP_VOLUME} uL on every A and T+Base transfer."
    )

    # One colour per group; every reagent keeps its own liquid definition and name.
    a_liquids = [
        protocol.define_liquid(
            name=f"A{i+1}",
            description=f"A{i+1} in C3 row {'ABCDEFGH'[i]}",
            display_color=A_COLOR,
        )
        for i in range(ROWS)
    ]
    t_liquids = [
        protocol.define_liquid(
            name=f"T{j+1} + Base",
            description=f"T{j+1} + Base premix in D3 column {j+1}",
            display_color=T_COLOR,
        )
        for j in range(COLS)
    ]
    dcm_liquid = protocol.define_liquid(
        name="DCM",
        description="DCM for tip pre-wetting; C2 A1 only, manually preloaded",
        display_color=DCM_COLOR,
    )
    dcm_reservoir.load_liquid(wells=[dcm_well], liquid=dcm_liquid, volume=DCM_VOLUME_LOADED)
    for idx, well in enumerate(plate_C3.columns()[0]):
        plate_C3.load_liquid(wells=[well], liquid=a_liquids[idx], volume=initial_A)
    plate_C3.load_empty(
        wells=[well for col in plate_C3.columns()[1:] for well in col]
    )
    # D3: one T+Base premix per column, T_source_volume uL in each of its 8 wells.
    for col_idx, col in enumerate(plate_D3.columns()):
        plate_D3.load_liquid(wells=col, liquid=t_liquids[col_idx], volume=T_source_volume)

    pipette.flow_rate.aspirate = p.asp_flow
    pipette.flow_rate.dispense = p.disp_flow

    def prewet_tips():
        """Pre-wet clean tips: 200 uL DCM per nozzle from C2 A1, dispensed back to C2 A1."""
        pipette.aspirate(PREWET_VOLUME, dcm_well.bottom(z=PREWET_ASP_HEIGHT))
        pipette.dispense(PREWET_VOLUME, dcm_well.bottom(z=PREWET_DISP_HEIGHT))

    # STAGE 1: no destination mixing, because all 8 tips return to the source
    # after each dispense and should not contact liquid in the receiving wells.
    protocol.comment(f"STAGE 1: distribute {volume_A} uL A across C3 (11 destinations, one tip set).")
    pipette.pick_up_tip()
    # One-time DCM pre-wet of the clean tips (only once for Stage 1).
    protocol.comment(f"STAGE 1 pre-wet 1/{N_PREWETS}: 200 uL DCM per nozzle, C2 A1 (clean tips).")
    prewet_tips()
    for j in range(1, COLS):
        # Aspirate A from C3 column 1, then withdraw above the source liquid and take the air gap.
        pipette.aspirate(volume_A, C3_columns[0].bottom(z=p.A_asp_height))
        pipette.air_gap(AIR_GAP_VOLUME, height=AIR_GAP_HEIGHT)
        if p.stage1_dispense_ref == "top":
            destination = C3_columns[j].top(z=-p.stage1_dispense_offset)
        else:
            destination = C3_columns[j].bottom(z=p.stage1_dispense_offset)
        # Dispense A plus the air gap in one stroke: clears the gap, nothing accumulates.
        pipette.dispense(volume_A + AIR_GAP_VOLUME, destination)
        protocol.comment(f"A distribution {j}/11: C3 column 1 -> column {j+1} (95 uL A + 25 uL air gap cleared).")
    pipette.drop_tip()

    # STAGE 2: T+Base premix added from D3, then destination mixing; new tips per T.
    protocol.comment(f"STAGE 2: add {volume_T} uL T+Base from D3 to C3 for 12 columns.")
    for j in range(COLS):
        pipette.pick_up_tip()
        protocol.comment(f"STAGE 2 pre-wet {j+2}/{N_PREWETS}: 200 uL DCM per nozzle, C2 A1 (clean tips).")
        prewet_tips()
        pipette.aspirate(volume_T, D3_columns[j].bottom(z=p.T_asp_height))
        pipette.air_gap(AIR_GAP_VOLUME, height=AIR_GAP_HEIGHT)
        # Dispense T+Base plus the air gap in one stroke into C3 so the tip is empty before mixing.
        pipette.dispense(volume_T + AIR_GAP_VOLUME, C3_columns[j].bottom(z=p.T_disp_height))
        if p.post_dispense_delay > 0:
            protocol.delay(seconds=p.post_dispense_delay)
        if p.mix_enabled:
            pipette.mix(
                repetitions=p.mix_reps,
                volume=p.mix_volume,
                location=C3_columns[j].bottom(z=p.mix_height),
            )
        pipette.drop_tip()
        protocol.comment(
            f"T+Base column {j+1}/12 complete: D3 col{j+1} -> C3 col{j+1}, "
            f"mix={p.mix_reps}x{p.mix_volume} uL if enabled."
        )

    protocol.comment(
        f"Complete: 96 C3 wells each ideally have {volume_A} uL A + "
        f"{volume_T} uL T+Base = {final_reaction} uL total. "
        "No dead volume or chemical reaction is simulated."
    )