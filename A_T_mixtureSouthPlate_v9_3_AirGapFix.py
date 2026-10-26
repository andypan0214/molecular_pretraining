"""Opentrons Flex: 8 A reagents x 12 T+Base premixes; protocol V9.3.

Deck:
    B3/B2: Flex 96-tip racks, 200 uL.
    C2: NEST 12-channel 15 mL reservoir, A1 only (DCM for tip pre-wet).
    C3: NEST 96 Deep Well 2 mL plate; reaction/destination plate.
    D3: NEST 12-channel 15 mL reservoir; one T+Base premix per channel A1-A12.
    A3: Trash bin.

Stage 1: Each C3 column 1 well (A1-H1) holds 12 x volume_A = 1140 uL.
         Distribute 95 uL of each A reagent to columns 2-12 (8 nozzles).
         One set of 8 tips, one DCM pre-wet, one air gap per dispense.
         Clear the air gap by blowing out in place after each A dispense.
         No destination mixing during A distribution.
Stage 2: Each D3 channel A1-A12 supplies 8 x 45 = 360 uL of its own
         T+Base premix to the corresponding C3 column. Use a fresh
         eight-tip set per channel and pre-wet that set with DCM once.
         Clear residual air in place before destination mixing.
         Each C3 destination undergoes 3 x 20 uL aspirate/dispense mixing
         if mix_enabled is True.

Default flow rates: aspirate 100 uL/s, dispense 200 uL/s (both stages).
Default final nominal per C3 well: 95 uL A + 45 uL T+Base = 140 uL.
Default D3 source volume: 360 uL per channel (ideal bookkeeping only).
D3 maximum configurable load: 12,000 uL per channel (80% of 15 mL).
Mixing uses the current C3 tip position after dispensing (no repeated well move).

IMPORTANT: 360 uL is an idealized source amount with no residual/dead volume.
It may not be physically aspiratable from a long reservoir trough at 1 mm
height. Confirm source height and adequate loading before real liquid runs.
Each post-transfer in-place blowout clears residual air from the reused tip.
Confirm air clearing, liquid accuracy, splash risk, and reagent compatibility
in Opentrons App and a validated liquid-only test.
Do not treat a passed syntax check as a successful Opentrons simulation.
"""
from opentrons import protocol_api

metadata = {
    "protocolName": "A x (T+Base): C3 Deep Well + D3 12-Channel Reservoir (V9.3)",
    "author": "OpentronsAI / Xu Lab review",
    "description": "C3 deep-well reaction plate, D3 12-channel T+Base reservoir; 95 uL A + 45 uL T+Base, one 8-tip set per source channel, 3x20 uL mix.",
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

        default=95.0, minimum=5.0, maximum=160.0, unit="uL",
    )
    parameters.add_float(
        variable_name="volume_T", display_name="T+Base volume per well",

        default=45.0, minimum=5.0, maximum=200.0, unit="uL",
    )
    parameters.add_float(
        variable_name="T_source_volume",
        display_name="D3 T+Base volume",
        default=360.0,
        minimum=360.0,
        maximum=12000.0,  # 80% of nominal 15 mL per channel
        unit="uL",
    )
    parameters.add_bool(
        variable_name="mix_enabled", display_name="Mix after premix dispense",

        default=True,
    )
    parameters.add_int(
        variable_name="mix_reps", display_name="Destination mix repetitions",

        default=3, minimum=1, maximum=20,
    )
    parameters.add_float(
        variable_name="mix_volume", display_name="Destination mix volume",

        default=20.0, minimum=5.0, maximum=200.0, unit="uL",
    )
    parameters.add_float(
        variable_name="A_asp_height", display_name="A source aspiration height",

        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="T_asp_height", display_name="Premix aspiration height",

        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_str(
        variable_name="stage1_dispense_ref", display_name="A dispense reference",

        choices=[
            {"display_name": "Below well top", "value": "top"},
            {"display_name": "Above well bottom", "value": "bottom"},
        ],
        default="top",
    )
    parameters.add_float(
        variable_name="stage1_dispense_offset", display_name="A dispense offset",

        default=2.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="T_disp_height", display_name="Premix dispense height",

        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="mix_height", display_name="Destination mixing height",

        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="asp_flow", display_name="Aspirate flow rate",

        default=100.0, minimum=1.0, maximum=716.0, unit="uL/s",
    )
    parameters.add_float(
        variable_name="disp_flow", display_name="Dispense flow rate",

        default=200.0, minimum=1.0, maximum=716.0, unit="uL/s",
    )
    parameters.add_float(
        variable_name="post_dispense_delay", display_name="Wait after T dispense",

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
    reservoir_D3 = protocol.load_labware(
        "nest_12_reservoir_15ml", "D3", label="T1-T12 + Base reservoir"
    )
    protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument(
        "flex_8channel_1000", "right", tip_racks=[tiprack_B3, tiprack_B2]
    )
    # The C3 A-row wells represent columns for eight parallel nozzles.
    # Each D3 A1-A12 is one long channel accessed by all eight nozzles.
    C3_columns = [col[0] for col in plate_C3.columns()]
    D3_channels = [reservoir_D3[f"A{i+1}"] for i in range(COLS)]
    if len(C3_columns) != COLS or len(D3_channels) != COLS:
        raise ValueError("Expected 12 C3 destination columns and 12 D3 source channels.")

    # DCM pre-wet source: C2 A1 is the ONLY reservoir channel used.
    dcm_well = dcm_reservoir["A1"]

    # ---- Validate before any liquid handling ----
    c3_well = plate_C3["A1"]
    d3_channel = reservoir_D3["A1"]
    tip_capacity = tiprack_B3["A1"].max_volume
    usable_capacity = min(pipette.max_volume, tip_capacity)
    min_volume = pipette.min_volume

    if initial_A > c3_well.max_volume:
        raise ValueError(f"12 x A = {initial_A} uL exceeds C3 source capacity.")
    if final_reaction > c3_well.max_volume:
        raise ValueError(f"A + T = {final_reaction} uL exceeds C3 well capacity.")
    # Each channel supplies eight tips at the same time, not one tip.
    theoretical_T_required = ROWS * volume_T
    if T_source_volume < theoretical_T_required:
        raise ValueError(
            f"D3 volume per channel ({T_source_volume} uL) is below "
            f"8 x {volume_T} = {theoretical_T_required} uL."
        )
    max_D3_load = 0.80 * d3_channel.max_volume
    if T_source_volume > max_D3_load:
        raise ValueError(
            f"D3 channel volume ({T_source_volume} uL) exceeds 80% "
            f"of defined capacity ({max_D3_load} uL)."
        )
    for label, amount in (("volume_A", volume_A), ("volume_T", volume_T)):
        if not min_volume <= amount <= usable_capacity:
            raise ValueError(
                f"{label}={amount} uL outside pipette/tip range "
                f"{min_volume}-{usable_capacity} uL."
            )
    # Tip capacity check includes the separately aspirated air gap.
    for label, amount in (("volume_A", volume_A), ("volume_T", volume_T)):
        if amount + AIR_GAP_VOLUME > usable_capacity:
            raise ValueError(
                f"{label} {amount} uL + {AIR_GAP_VOLUME} uL air gap exceeds the "
                f"{usable_capacity} uL tip capacity."
            )
    if PREWET_VOLUME > usable_capacity:
        raise ValueError(f"Pre-wet volume {PREWET_VOLUME} uL exceeds tip capacity {usable_capacity} uL.")

    # DCM pre-wet validation: eight nozzles cycle through C2 A1 at once.
    prewet_volume_per_operation = N_NOZZLES * PREWET_VOLUME            # 1,600 uL
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
        ("T_asp_height", p.T_asp_height, d3_channel.depth),
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
        "TEST CONFIGURATION: D3 has 360 uL per channel by default (idealized, "
        "zero dead volume). Confirm aspiration height and sufficient liquid "
        "before physical runs; verify compatibility and robot positions."
    )
    protocol.comment(
        f"Target per C3 well: {volume_A} uL A + {volume_T} uL T+Base = "
        f"{final_reaction} uL. C3 column 1 initially {initial_A} uL per well; "
        f"D3 loaded with {T_source_volume} uL per reservoir channel "
        f"(8 x {volume_T} = {theoretical_T_required} uL transferred). Mixing: "
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
            description=f"T{j+1} + Base premix in D3 channel A{j+1}",
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
    # D3: exactly one premix liquid per long reservoir channel A1-A12.
    # One simultaneous eight-tip transfer withdraws 8 x volume_T from that channel.
    for j, channel in enumerate(D3_channels):
        reservoir_D3.load_liquid(
            wells=[channel], liquid=t_liquids[j], volume=T_source_volume
        )

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
        # Dispense the reagent, then clear retained air in place before
        # reusing these same eight tips for the next source aspiration.
        pipette.dispense(volume_A, destination)
        pipette.blow_out()  # stays at the C3 destination; does not discard tips
        protocol.comment(
            f"A distribution {j}/11: C3 column 1 -> column {j+1} "
            f"({volume_A} uL A, {AIR_GAP_VOLUME} uL air gap, in-place blowout)."
        )
    pipette.drop_tip()

    # STAGE 2: One T+Base reservoir channel feeds the matching C3 column.
    # New eight-tip set per channel, followed by destination mixing.
    protocol.comment(f"STAGE 2: add {volume_T} uL T+Base from D3 to C3 for 12 columns.")
    for j in range(COLS):
        pipette.pick_up_tip()
        protocol.comment(f"STAGE 2 pre-wet {j+2}/{N_PREWETS}: 200 uL DCM per nozzle, C2 A1 (clean tips).")
        prewet_tips()
        pipette.aspirate(volume_T, D3_channels[j].bottom(z=p.T_asp_height))
        pipette.air_gap(AIR_GAP_VOLUME, height=AIR_GAP_HEIGHT)
        # Dispense T+Base into C3 and expel retained air before mixing.
        # Blow out at the current C3 well position (no additional gantry move).
        pipette.dispense(volume_T, C3_columns[j].bottom(z=p.T_disp_height))
        pipette.blow_out()
        if p.post_dispense_delay > 0:
            protocol.delay(seconds=p.post_dispense_delay)
        if p.mix_enabled:
            # Avoid another location-targeted move after the dispense.
            # By default T_disp_height == mix_height, so mix directly in place.
            # If heights differ, move vertically WITHIN the same well, without
            # the default arc that can retract the tip above the well.
            if abs(p.mix_height - p.T_disp_height) > 1e-6:
                pipette.move_to(
                    C3_columns[j].bottom(z=p.mix_height), force_direct=True
                )
            pipette.mix(
                repetitions=p.mix_reps,
                volume=p.mix_volume,
            )
        pipette.drop_tip()
        protocol.comment(
            f"T+Base channel A{j+1}/12 complete: D3 A{j+1} -> C3 col{j+1}, "
            f"mix={p.mix_reps}x{p.mix_volume} uL if enabled."
        )

    protocol.comment(
        f"Complete: 96 C3 wells each ideally have {volume_A} uL A + "
        f"{volume_T} uL T+Base = {final_reaction} uL total. "
        "No dead volume or chemical reaction is simulated."
    )