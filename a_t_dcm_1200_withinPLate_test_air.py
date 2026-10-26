from opentrons import protocol_api

metadata = {
    'protocolName': 'R1 Acid Redissolution (Flex, 8-channel)',
    'author': 'OpentronsAI',
    'description': (
        'R1 acid redissolution: adds 8 x 150 uL solvent (DCM intended; water for '
        'initial test) per destination well, 1,200 uL total per well, to each '
        'column of a NEST 96 deep well plate containing dried R1 products. '
        'One source tip pre-wetting operation is performed per destination column '
        '(default 200 uL per nozzle, aspirated from and dispensed back into the '
        'same reservoir channel); the pre-wet volume is automatically reduced, or '
        'pre-wetting is skipped, if insufficient accessible source liquid is '
        'estimated. A 25 uL air gap is drawn after every solvent aspiration. '
        'Transfers 1-7 are dispensed non-contact at a set clearance above the '
        'predicted destination liquid meniscus. Transfer 8 is dispensed inside '
        'the liquid and followed by a single mix.'
    ),
    'source': 'OpentronsAI',
}

requirements = {
    'robotType': 'Flex',
    'apiLevel': '2.28',
}


def add_parameters(parameters: protocol_api.ParameterContext):
    # ---- Dispensing parameters ----
    parameters.add_float(
        display_name='Meniscus clearance',
        variable_name='meniscus_clearance',
        default=3.0,
        minimum=0.5,
        maximum=20.0,
        unit='mm',
        description='Clearance above predicted liquid surface for transfers 1-7.',
    )
    parameters.add_float(
        display_name='8th dispense height',
        variable_name='eighth_bottom_height',
        default=4.0,
        minimum=1.0,
        maximum=30.0,
        unit='mm',
        description='Height above well bottom for dispense of transfer 8 (in liquid).',
    )
    parameters.add_float(
        display_name='Source aspirate height',
        variable_name='source_asp_height',
        default=2.0,
        minimum=1.0,
        maximum=25.0,
        unit='mm',
        description='Height above reservoir well bottom for aspiration.',
    )
    parameters.add_float(
        display_name='Mix height',
        variable_name='mix_bottom_height',
        default=3.0,
        minimum=1.0,
        maximum=30.0,
        unit='mm',
        description='Height above well bottom for the final mix.',
    )
    parameters.add_int(
        display_name='Mix repetitions',
        variable_name='mix_reps',
        default=5,
        minimum=1,
        maximum=20,
        description='Number of mix cycles after transfer 8.',
    )
    parameters.add_float(
        display_name='Mix volume',
        variable_name='mix_volume',
        default=150.0,
        minimum=10.0,
        maximum=175.0,
        unit='uL',
        description='Volume per mix cycle (must not exceed tip capacity of 200 uL).',
    )

    # ---- Air-gap parameters ----
    parameters.add_float(
        display_name='Air gap volume',
        variable_name='air_gap_volume',
        default=25.0,
        minimum=0.0,
        maximum=50.0,
        unit='uL',
        description='Air gap drawn after every solvent aspiration.',
    )
    parameters.add_float(
        display_name='Air gap height',
        variable_name='air_gap_height',
        default=20.0,
        minimum=2.0,
        maximum=60.0,
        unit='mm',
        description='Height above the source reservoir well rim for the air gap.',
    )

    # ---- Pre-wetting parameters ----
    parameters.add_bool(
        display_name='Enable pre-wet',
        variable_name='prewet_enabled',
        default=True,
        description='Pre-wet tips in the source channel before transfers.',
    )
    parameters.add_float(
        display_name='Pre-wet volume',
        variable_name='prewet_volume',
        default=200.0,
        minimum=10.0,
        maximum=200.0,
        unit='uL',
        description='Pre-wet volume per nozzle (aspirated, then returned to source).',
    )
    parameters.add_int(
        display_name='Pre-wet repetitions',
        variable_name='prewet_reps',
        default=1,
        minimum=1,
        maximum=5,
        description='Number of pre-wet aspirate/dispense cycles per column.',
    )
    parameters.add_bool(
        display_name='Adaptive pre-wet',
        variable_name='adaptive_prewet',
        default=True,
        description='Reduce or skip pre-wet if source liquid is insufficient.',
    )

    # ---- Flow rates (existing) ----
    parameters.add_float(
        display_name='Aspirate flow rate',
        variable_name='asp_flow_rate',
        default=100.0,
        minimum=5.0,
        maximum=716.0,
        unit='uL/s',
        description='Aspirate flow rate. Initial test value, not validated for DCM.',
    )
    parameters.add_float(
        display_name='Dispense flow rate',
        variable_name='disp_flow_rate',
        default=100.0,
        minimum=5.0,
        maximum=716.0,
        unit='uL/s',
        description='Dispense flow rate. Initial test value, not validated for DCM.',
    )


def run(protocol: protocol_api.ProtocolContext):
    # ---- Runtime parameters ----
    MENISCUS_CLEARANCE = protocol.params.meniscus_clearance
    EIGHTH_BOTTOM_HEIGHT = protocol.params.eighth_bottom_height
    SOURCE_ASP_HEIGHT = protocol.params.source_asp_height
    MIX_BOTTOM_HEIGHT = protocol.params.mix_bottom_height
    MIX_REPS = protocol.params.mix_reps
    MIX_VOLUME = protocol.params.mix_volume
    AIR_GAP_VOLUME = protocol.params.air_gap_volume
    AIR_GAP_HEIGHT = protocol.params.air_gap_height
    PREWET_ENABLED = protocol.params.prewet_enabled
    PREWET_VOLUME = protocol.params.prewet_volume
    PREWET_REPS = protocol.params.prewet_reps
    ADAPTIVE_PREWET = protocol.params.adaptive_prewet
    ASP_FLOW = protocol.params.asp_flow_rate
    DISP_FLOW = protocol.params.disp_flow_rate

    # ---- Fixed constants ----
    NUM_COLUMNS = 12
    TRANSFERS_PER_COLUMN = 8
    TRANSFER_VOL = 150            # uL per nozzle per transfer
    RESERVOIR_START_VOL = 11000   # uL per reservoir channel
    NUM_NOZZLES = 8

    # ---- Labware ----
    # Deck: A3 trash, B3 tips, C3 reservoir, D3 destination plate
    trash = protocol.load_trash_bin('A3')
    tiprack = protocol.load_labware('opentrons_flex_96_tiprack_200ul', 'B3')
    reservoir = protocol.load_labware('nest_12_reservoir_15ml', 'C3')
    dest_plate = protocol.load_labware('nest_96_wellplate_2ml_deep', 'D3')

    # ---- Pipette (standard 8-nozzle configuration) ----
    pipette = protocol.load_instrument(
        'flex_8channel_1000', 'right', tip_racks=[tiprack]
    )
    pipette.flow_rate.aspirate = ASP_FLOW
    pipette.flow_rate.dispense = DISP_FLOW

    # ---- Liquids (visualization + volume tracking for meniscus() ) ----
    solvent = protocol.define_liquid(
        name='Solvent (DCM intended; water for initial test)',
        description='Manually pre-filled, 11,000 uL per reservoir channel',
        display_color='#3399FF',
    )
    reservoir.load_liquid(
        wells=reservoir.wells(),
        volume=RESERVOIR_START_VOL,
        liquid=solvent,
    )
    dest_plate.load_empty(dest_plate.wells())

    # ---- Geometry / capacity checks (values read from labware definitions) ----
    sample_well = dest_plate['A1']
    well_depth = sample_well.depth
    well_len = sample_well.length
    well_wid = sample_well.width
    tip_cap = tiprack.wells()[0].max_volume
    res_well = reservoir['A1']
    res_len = res_well.length   # x dimension (mm), rectangular well
    res_wid = res_well.width    # y dimension (mm), rectangular well
    res_depth = res_well.depth

    OCCUPANCY = TRANSFER_VOL + AIR_GAP_VOLUME
    if OCCUPANCY > tip_cap:
        raise ValueError(
            f'Transfer ({TRANSFER_VOL}) + air gap ({AIR_GAP_VOLUME}) = {OCCUPANCY} uL '
            f'exceeds tip capacity ({tip_cap} uL).'
        )
    if PREWET_VOLUME > tip_cap:
        raise ValueError('Pre-wet volume exceeds tip capacity.')
    if MIX_VOLUME > tip_cap:
        raise ValueError('Mix volume exceeds tip capacity.')
    if SOURCE_ASP_HEIGHT >= res_depth:
        raise ValueError('Source aspirate height is at/above the reservoir depth.')

    # Rectangular-prism approximation of destination liquid height (ignores
    # V-bottom). ESTIMATE ONLY, used for a rim-clearance sanity check; actual
    # meniscus() placement uses the API's own volume tracking.
    if well_len and well_wid:
        area = well_len * well_wid  # mm^2 (1 uL = 1 mm^3)
        h_after_7 = (7 * TRANSFER_VOL) / area
        h_after_8 = (8 * TRANSFER_VOL) / area
        protocol.comment(
            f'Geometry (from labware def): dest depth={well_depth:.2f} mm, '
            f'well={well_len:.2f}x{well_wid:.2f} mm.'
        )
        protocol.comment(
            f'ESTIMATE ONLY (prism approx): liquid height after transfer 7 '
            f'~{h_after_7:.1f} mm, after transfer 8 ~{h_after_8:.1f} mm '
            f'(of {well_depth:.1f} mm depth).'
        )
        if h_after_8 >= well_depth:
            raise ValueError(
                'Estimated liquid height after 1,200 uL exceeds well depth; '
                'wells may overflow.'
            )
        if h_after_7 + MENISCUS_CLEARANCE >= well_depth:
            protocol.comment(
                'WARNING: predicted meniscus + clearance for transfer 7 is at/above '
                'the well rim; non-contact dispensing height will be near/above the rim.'
            )
        if EIGHTH_BOTTOM_HEIGHT >= well_depth:
            raise ValueError('eighth_bottom_height is at/above the well rim.')
        # Sanity: 8th dispense height should be below the estimated surface so the
        # tip is in liquid (intended behavior); warn if not.
        if EIGHTH_BOTTOM_HEIGHT > h_after_7:
            protocol.comment(
                'NOTE: eighth_bottom_height is above the estimated liquid level '
                'after transfer 7; transfer 8 may not be dispensed below the surface.'
            )

    protocol.comment(
        'Reminder: water testing does not establish chemical compatibility with DCM.'
    )

    # ---- Source liquid estimate (starts at fixed RESERVOIR_START_VOL per channel) ----
    # Estimated remaining volume per reservoir channel. Each channel supplies only
    # its own column, so each starts at RESERVOIR_START_VOL.
    source_est_vol = {i: float(RESERVOIR_START_VOL) for i in range(NUM_COLUMNS)}

    # Known unusable residual volume: NOT validated for this labware/liquid.
    # Kept at 0 per instructions (do not invent a physical dead-volume value).
    KNOWN_UNUSABLE_RESIDUAL_UL = 0.0

    def accessible_source_volume(col_idx):
        """Estimated liquid (uL) in the channel above the aspiration height.

        Uses rectangular-prism geometry for the reservoir channel (length x width
        from the labware definition) and the aspirate height above the well bottom.
        Returns None if the geometry cannot be determined reliably.
        """
        if not (res_len and res_wid):
            return None
        below_tip_ul = res_len * res_wid * SOURCE_ASP_HEIGHT  # mm^3 == uL
        # NOTE: V-bottom geometry is ignored, so this is an estimate only.
        return source_est_vol[col_idx] - below_tip_ul - KNOWN_UNUSABLE_RESIDUAL_UL

    def plan_prewet(col_idx):
        """Return (volume_per_nozzle, reason) for the pre-wet of this column.

        volume_per_nozzle == 0 means skip pre-wetting.
        Pre-wet liquid is returned before the transfers, so future transfer volumes
        are NOT subtracted when sizing the temporary withdrawal. However, the
        source must still be able to support the required transfers afterwards.
        """
        if not PREWET_ENABLED:
            return 0.0, 'pre-wetting disabled by parameter'

        accessible = accessible_source_volume(col_idx)
        required_for_transfers = TRANSFERS_PER_COLUMN * TRANSFER_VOL * NUM_NOZZLES

        if accessible is None:
            return 0.0, (
                'reservoir geometry unavailable; accessible source volume cannot be '
                'reliably calculated (limitation)'
            )

        # Feasibility of required transfers (independent of pre-wet).
        if accessible < required_for_transfers:
            return 0.0, (
                f'estimated accessible source ({accessible:.0f} uL) is below the '
                f'{required_for_transfers} uL needed for the transfers; pre-wet '
                f'skipped so as not to consume liquid needed for transfers'
            )

        # Max temporary withdrawal per nozzle supported by accessible liquid.
        max_per_nozzle = accessible / NUM_NOZZLES
        # Pre-wet is returned before transfers; also never exceed tip capacity.
        vol = min(PREWET_VOLUME, tip_cap, max_per_nozzle)

        if vol < PREWET_VOLUME and not ADAPTIVE_PREWET:
            return 0.0, (
                f'insufficient accessible source for {PREWET_VOLUME} uL/nozzle '
                f'and adaptive pre-wetting is off'
            )
        if vol <= 0:
            return 0.0, 'no safe positive pre-wet volume available'
        return vol, (
            'full requested volume' if vol >= PREWET_VOLUME
            else f'reduced from {PREWET_VOLUME} uL to {vol:.1f} uL per nozzle '
                 f'(accessible source estimate {accessible:.0f} uL)'
        )

    def preflight_transfer_feasibility(col_idx):
        """Verify the source can supply the required transfers for this column."""
        accessible = accessible_source_volume(col_idx)
        need = TRANSFERS_PER_COLUMN * TRANSFER_VOL * NUM_NOZZLES
        if accessible is not None and accessible < need:
            raise ValueError(
                f'Column {col_idx + 1}: estimated accessible source '
                f'({accessible:.0f} uL) is less than the {need} uL required for '
                f'{TRANSFERS_PER_COLUMN} x {TRANSFER_VOL} uL x {NUM_NOZZLES} nozzles. '
                f'Refill reservoir channel A{col_idx + 1}.'
            )

    # ---- Workflow: one destination column per iteration ----
    for col_idx in range(NUM_COLUMNS):
        src_well = reservoir.wells()[col_idx]            # A1..A12 (matching channel)
        dest_well = dest_plate.columns()[col_idx][0]     # row A well of column (primary channel)

        # Required transfers must be feasible, otherwise stop before picking up tips.
        preflight_transfer_feasibility(col_idx)

        pipette.pick_up_tip()

        # ---- Source tip pre-wetting (once per column) ----
        prewet_vol, reason = plan_prewet(col_idx)
        if prewet_vol > 0:
            protocol.comment(
                f'Column {col_idx + 1}: pre-wetting {prewet_vol:.1f} uL/nozzle '
                f'({NUM_NOZZLES * prewet_vol:.0f} uL total, returned to source), '
                f'{PREWET_REPS} rep(s): {reason}.'
            )
            for _ in range(PREWET_REPS):
                pipette.aspirate(prewet_vol, src_well.bottom(z=SOURCE_ASP_HEIGHT))
                # Return the SAME volume to the SAME reservoir channel.
                pipette.dispense(prewet_vol, src_well.bottom(z=SOURCE_ASP_HEIGHT))
                # Net source change is zero, so source_est_vol is unchanged.
        else:
            protocol.comment(
                f'Column {col_idx + 1}: pre-wetting skipped. Reason: {reason}.'
            )

        # ---- Transfers 1-7: non-contact dispense above predicted meniscus ----
        for _ in range(TRANSFERS_PER_COLUMN - 1):
            pipette.aspirate(TRANSFER_VOL, src_well.bottom(z=SOURCE_ASP_HEIGHT))
            if AIR_GAP_VOLUME > 0:
                pipette.air_gap(AIR_GAP_VOLUME, height=AIR_GAP_HEIGHT)
            # meniscus(target="end") keeps the tip above the surface after the
            # dispense, using the destination volume tracked by the API.
            pipette.dispense(
                TRANSFER_VOL + AIR_GAP_VOLUME,
                dest_well.meniscus(z=MENISCUS_CLEARANCE, target="end"),
            )
            source_est_vol[col_idx] -= TRANSFER_VOL * NUM_NOZZLES

        # ---- Transfer 8: aspirate, air gap, dispense inside the liquid ----
        pipette.aspirate(TRANSFER_VOL, src_well.bottom(z=SOURCE_ASP_HEIGHT))
        if AIR_GAP_VOLUME > 0:
            pipette.air_gap(AIR_GAP_VOLUME, height=AIR_GAP_HEIGHT)
        pipette.dispense(
            TRANSFER_VOL + AIR_GAP_VOLUME,
            dest_well.bottom(z=EIGHTH_BOTTOM_HEIGHT),
        )
        source_est_vol[col_idx] -= TRANSFER_VOL * NUM_NOZZLES

        # Final mix (only after transfer 8), same tips, no reservoir contact afterwards
        pipette.mix(MIX_REPS, MIX_VOLUME, dest_well.bottom(z=MIX_BOTTOM_HEIGHT))

        # Discard tips immediately after mixing
        pipette.drop_tip()