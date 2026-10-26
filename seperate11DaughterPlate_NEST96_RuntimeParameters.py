"""Opentrons Flex: transfer one 96-well R1 mother plate to one daughter plate.

Deck: A3 trash, B3 200-uL tips, C3 NEST 96 deep-well 2 mL mother,
      D3 NEST 96 deep-well 2 mL plate.

Defaults intentionally preserve the user's working daughter-plate protocol:
- One new 8-tip set per source column (12 sets; 96 tips total).
- Pre-wet 200 uL from the same 8 mother wells, return to the same wells once.
- Aspirate 20 uL from each mother well; draw a 25 uL air gap.
- Dispense 20 uL liquid plus 25 uL air (45 uL commanded) into the matching D3 well.
- No mixing, no pause, one daughter plate per run.

D3 position offset REFERENCE: X +0.6, Y +0.3, Z +3.4 mm. Apply in the
Opentrons App via Labware Position Check, not again in this Python protocol.
The offset is independent of the bottom/top-relative dispensing height.

Changes to runtime parameters require analysis and a physical water test.
No official Opentrons simulation is implied by a local syntax check.
"""
from opentrons import protocol_api

metadata = {
    "protocolName": "R1 Mother to Daughter - NEST Deep Well (adjustable)",
    "author": "OpentronsAI / Xu Lab adaptation",
    "description": "One R1 daughter plate; prewet and 20 uL transfer, adjustable runtime parameters.",
    "source": "OpentronsAI / Xu Lab",
}

requirements = {"robotType": "Flex", "apiLevel": "2.28"}


def add_parameters(parameters: protocol_api.ParameterContext):
    # No parameter descriptions: avoids Opentrons' 100-character description limit.
    # All parameter display names are <= 30 characters.
    parameters.add_float(
        variable_name="mother_initial_volume", display_name="Mother initial volume",
        default=1200.0, minimum=220.0, maximum=2000.0, unit="uL",
    )
    parameters.add_float(
        variable_name="transfer_volume", display_name="Daughter transfer volume",
        default=20.0, minimum=5.0, maximum=150.0, unit="uL",
    )
    parameters.add_bool(
        variable_name="prewet_enabled", display_name="Enable mother pre-wet",
        default=True,
    )
    parameters.add_float(
        variable_name="prewet_volume", display_name="Pre-wet volume",
        default=200.0, minimum=5.0, maximum=200.0, unit="uL",
    )
    parameters.add_float(
        variable_name="source_asp_height", display_name="Mother aspiration height",
        default=2.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="prewet_return_height", display_name="Pre-wet return height",
        default=4.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="air_gap_volume", display_name="Air gap volume",
        default=25.0, minimum=0.0, maximum=100.0, unit="uL",
    )
    parameters.add_float(
        variable_name="air_gap_height", display_name="Air gap above well top",
        default=5.0, minimum=2.0, maximum=50.0, unit="mm",
    )
    parameters.add_str(
        variable_name="dispense_reference", display_name="Daughter dispense reference",
        choices=[
            {"display_name": "Above well bottom", "value": "bottom"},
            {"display_name": "Below well top", "value": "top"},
        ],
        default="bottom",
    )
    parameters.add_float(
        variable_name="dispense_offset", display_name="Daughter dispense offset",
        default=3.0, minimum=1.0, maximum=40.0, unit="mm",
    )
    parameters.add_float(
        variable_name="asp_flow", display_name="Aspirate flow rate",
        default=100.0, minimum=5.0, maximum=716.0, unit="uL/s",
    )
    parameters.add_float(
        variable_name="disp_flow", display_name="Dispense flow rate",
        default=100.0, minimum=5.0, maximum=716.0, unit="uL/s",
    )
    parameters.add_float(
        variable_name="post_dispense_delay", display_name="Wait after dispense",
        default=0.0, minimum=0.0, maximum=10.0, unit="s",
    )
    parameters.add_bool(
        variable_name="mix_enabled", display_name="Mix daughter after dispense",
        default=False,
    )
    parameters.add_int(
        variable_name="mix_reps", display_name="Daughter mix repetitions",
        default=3, minimum=1, maximum=20,
    )
    parameters.add_float(
        variable_name="mix_volume", display_name="Daughter mix volume",
        default=10.0, minimum=5.0, maximum=100.0, unit="uL",
    )
    parameters.add_float(
        variable_name="mix_height", display_name="Daughter mix height",
        default=1.0, minimum=1.0, maximum=40.0, unit="mm",
    )


def run(protocol: protocol_api.ProtocolContext):
    p = protocol.params
    NUM_COLUMNS = 12

    # Labware Position Check offsets are NOT hard-coded here.
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_200ul", "B3")
    mother_plate = protocol.load_labware(
        "nest_96_wellplate_2ml_deep", "C3", label="R1 mother plate"
    )
    daughter_plate = protocol.load_labware(
        "nest_96_wellplate_2ml_deep", "D3", label="R1 daughter NEST 2 mL"
    )
    protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument(
        "flex_8channel_1000", "right", tip_racks=[tiprack]
    )

    # Reject physically/instrumentally invalid parameter combinations before tip pickup.
    source = mother_plate["A1"]
    destination = daughter_plate["A1"]
    tip_capacity = min(tiprack["A1"].max_volume, pipette.max_volume)
    if p.mother_initial_volume > source.max_volume:
        raise ValueError("Mother initial volume exceeds C3 well capacity.")
    if p.transfer_volume > p.mother_initial_volume:
        raise ValueError("Transfer volume exceeds mother initial volume.")
    if p.transfer_volume > destination.max_volume:
        raise ValueError("Transfer volume exceeds daughter well capacity.")
    if p.transfer_volume < pipette.min_volume:
        raise ValueError("Transfer volume is below pipette minimum volume.")
    if p.transfer_volume + p.air_gap_volume > tip_capacity:
        raise ValueError("Transfer plus air gap exceeds the installed tip capacity.")
    if p.prewet_enabled:
        if not pipette.min_volume <= p.prewet_volume <= tip_capacity:
            raise ValueError("Pre-wet volume outside pipette/tip working range.")
        if p.prewet_volume > p.mother_initial_volume:
            raise ValueError("Pre-wet volume exceeds mother initial volume.")
    for name, z, depth in (
        ("source_asp_height", p.source_asp_height, source.depth),
        ("prewet_return_height", p.prewet_return_height, source.depth),
        ("dispense_offset", p.dispense_offset, destination.depth),
    ):
        if not 0 < z < depth:
            raise ValueError(f"{name} must be >0 and < well depth ({depth} mm).")
    if p.mix_enabled:
        if not pipette.min_volume <= p.mix_volume <= min(p.transfer_volume, tip_capacity):
            raise ValueError("Daughter mix volume exceeds available liquid or pipette range.")
        if not 0 < p.mix_height < destination.depth:
            raise ValueError("Daughter mixing height must be inside the well.")

    pipette.flow_rate.aspirate = p.asp_flow
    pipette.flow_rate.dispense = p.disp_flow

    # Tracking: one run = one daughter plate, 96 mother wells mapped 1:1.
    r1 = protocol.define_liquid(
        name="R1", description="R1 in mother plate", display_color="#33AAFF"
    )
    mother_plate.load_liquid(
        wells=mother_plate.wells(), volume=p.mother_initial_volume, liquid=r1
    )
    daughter_plate.load_empty(wells=daughter_plate.wells())

    protocol.comment(
        f"ONE daughter plate: {p.transfer_volume} uL/well, "
        f"pre-wet={p.prewet_enabled} ({p.prewet_volume} uL), "
        f"air gap={p.air_gap_volume} uL, mix={p.mix_enabled}."
    )

    for col in range(NUM_COLUMNS):
        src = mother_plate.columns()[col][0]  # 8 channels access A-H in same column
        dst = daughter_plate.columns()[col][0]

        pipette.pick_up_tip()

        if p.prewet_enabled:
            # Same tips, same eight mother wells; liquid is returned before transfer.
            pipette.aspirate(p.prewet_volume, src.bottom(z=p.source_asp_height))
            pipette.dispense(p.prewet_volume, src.bottom(z=p.prewet_return_height))

        pipette.aspirate(p.transfer_volume, src.bottom(z=p.source_asp_height))
        if p.air_gap_volume > 0:
            pipette.air_gap(p.air_gap_volume, height=p.air_gap_height)

        if p.dispense_reference == "top":
            dispense_location = dst.top(z=-p.dispense_offset)
        else:
            dispense_location = dst.bottom(z=p.dispense_offset)

        # Preserve working baseline: dispense the aspirated liquid + air volume.
        # The air gap is NOT extra liquid. Fresh tips are used for each column.
        pipette.dispense(p.transfer_volume + p.air_gap_volume, dispense_location)

        if p.post_dispense_delay > 0:
            protocol.delay(seconds=p.post_dispense_delay)

        if p.mix_enabled:
            # Disabled by default. Verify 20-uL liquid depth before enabling.
            pipette.mix(
                repetitions=p.mix_reps,
                volume=p.mix_volume,
                location=dst.bottom(z=p.mix_height),
            )

        pipette.drop_tip()

    protocol.comment(
        f"Complete: 96 daughter wells with {p.transfer_volume} uL nominal each; "
        f"mother {p.mother_initial_volume - p.transfer_volume} uL/well nominal remaining."
    )
