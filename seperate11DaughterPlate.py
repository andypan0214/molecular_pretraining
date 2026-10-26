from opentrons import protocol_api

metadata = {
    "protocolName": "R1 Mother to Daughter Aliquoting",
    "author": "OpentronsAI",
    "description": "Pre-wet and transfer 20 uL from a 96-well R1 mother plate to one daughter PCR plate with an 8-channel pipette.",
    "source": "OpentronsAI",
}

requirements = {
    "robotType": "Flex",
    "apiLevel": "2.28",
}


def add_parameters(parameters):
    parameters.add_float(
        variable_name="mother_initial_volume",
        display_name="Mother initial volume",
        description="Starting R1 volume in each mother well before this run.",
        default=1200.0,
        minimum=220.0,
        maximum=2000.0,
        unit="uL",
    )


def run(protocol: protocol_api.ProtocolContext):
    # ------------------------------------------------------------------
    # Constants
    # ------------------------------------------------------------------
    PREWET_VOLUME = 200.0     # uL per nozzle, returned to the same mother well
    TRANSFER_VOLUME = 20.0    # uL per nozzle, dispensed into the daughter plate
    AIR_GAP_VOLUME = 25.0     # uL per nozzle, drawn after the liquid aspirate
    FLOW_RATE = 100.0         # uL/s, initial test value for aspirate and dispense
    NUM_COLUMNS = 12

    # Source and destination heights (mm). Labware offsets from Labware
    # Position Check are applied automatically; no manual offset is added here.
    SRC_ASPIRATE_Z = 2.0      # above bottom of 2 mL deep well, for 20 uL aspirate
    SRC_PREWET_RETURN_Z = 4.0 # slightly higher for the pre-wet return, to limit splashing
    DEST_DISPENSE_Z = 3.0     # above bottom of PCR strip well; avoids tip-bottom contact
    AIR_GAP_HEIGHT = 5.0      # mm above the top of the mother well

    mother_initial_volume = protocol.params.mother_initial_volume

    # ------------------------------------------------------------------
    # Labware
    # ------------------------------------------------------------------
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_200ul", "B3")
    mother_plate = protocol.load_labware(
        "nest_96_wellplate_2ml_deep", "C3", label="R1 mother plate"
    )
    daughter_plate = protocol.load_labware(
        "opentrons_96_aluminumblock_generic_pcr_strip_200ul",
        "D3",
        label="Daughter PCR plate",
    )

    # Trash bin
    trash = protocol.load_trash_bin("A3")

    # Pipette
    pipette = protocol.load_instrument(
        "flex_8channel_1000", "right", tip_racks=[tiprack]
    )
    pipette.flow_rate.aspirate = FLOW_RATE
    pipette.flow_rate.dispense = FLOW_RATE

    # ------------------------------------------------------------------
    # Liquid tracking (for app visualization)
    # ------------------------------------------------------------------
    r1_liquid = protocol.define_liquid(
        name="R1",
        description="R1 in the mother plate; each well is a distinct sample",
        display_color="#33AAFF",
    )
    mother_plate.load_liquid(
        wells=mother_plate.wells(),
        volume=mother_initial_volume,
        liquid=r1_liquid,
    )
    daughter_plate.load_empty(wells=daughter_plate.wells())

    # ------------------------------------------------------------------
    # Transfers: one fresh set of 8 tips per column
    # ------------------------------------------------------------------
    for col in range(NUM_COLUMNS):
        src = mother_plate.columns()[col][0]    # row A well; the 8-channel covers A-H
        dest = daughter_plate.columns()[col][0]

        # 1. Fresh set of eight tips
        pipette.pick_up_tip()

        # 2-3. One-time pre-wet: 200 uL from the mother column, returned to the same wells
        pipette.aspirate(PREWET_VOLUME, src.bottom(z=SRC_ASPIRATE_Z))
        pipette.dispense(PREWET_VOLUME, src.bottom(z=SRC_PREWET_RETURN_Z))

        # 4. Aspirate 20 uL liquid from the mother column
        pipette.aspirate(TRANSFER_VOLUME, src.bottom(z=SRC_ASPIRATE_Z))

        # 5. Withdraw above the liquid and aspirate the 25 uL air gap
        pipette.air_gap(AIR_GAP_VOLUME, height=AIR_GAP_HEIGHT)

        # 6. Dispense everything (20 uL liquid + 25 uL air = 45 uL) into the daughter
        #    column. This fully empties the tip, so the default Flex push-out applies.
        pipette.dispense(
            TRANSFER_VOLUME + AIR_GAP_VOLUME,
            dest.bottom(z=DEST_DISPENSE_Z),
        )

        # 7-8. Tip is empty; drop it directly into the trash
        pipette.drop_tip()