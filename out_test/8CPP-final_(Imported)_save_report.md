# Layout report

Footprint: 303 x 425 = 128,775 tiles
Fully routed: NO

## Machines
- 8 x Coal Power Plant (r_coal_power_plant_01, planner 8.0000, 100x42)  <- recipe not in recipes.json, inferred
- 1 x Exhaust Stack (r_exhaust_stack_01, planner 0.3100, 24x24)
- 8 x Vertical Heat Exchanger (r_vertical_heat_exchanger_02, planner 8.0000, 14x14)  <- recipe not in recipes.json, inferred
- 16 x Modular Turbine (5 LPT, 0 HPT) (r_modular_turbine_01, planner 16.0000, 118x12)  <- recipe not in recipes.json, inferred
- 4 x Steam Condenser (r_steam_condenser_01, planner 4.0000, 52x16)  <- recipe not in recipes.json, inferred
- 8 x Mineshaft Drill (r_mineshaft_drill_01, planner 7.6632, 14x14)  <- recipe not in recipes.json, inferred
- 8 x Polisher (r_polisher_01, planner 8.0000, 28x12)  <- recipe not in recipes.json, inferred
- 40 x Electrolysis Plant (r_electrolysis_plant_02, planner 40.0000, 6x10)
- 2 x Atmospheric Distillation Plant (r_atmospheric_distillation_plant_02, planner 1.3333, 16x16)
- 7 x Water Pump2 (r_water_pump2_01, planner 6.8226, 4x4)
- 1 x Tree Farm (88 trees) (r_tree_farm_01, planner 0.9221, 64x36)  <- recipe not in recipes.json, inferred
- 1 x Blast Furnace MK2 (r_blast_furnace_MK2_03, planner 0.8530, 16x16)
- 15 x Electrolysis Plant (r_electrolysis_plant_01, planner 14.8148, 6x10)
- 1 x Air Separation Unit (r_air_separation_unit_01, planner 0.3292, 29x24)  <- recipe not in recipes.json, inferred
- 1 x Chemical Plant (r_chemical_plant_15, planner 0.8889, 23x24)  <- recipe not in recipes.json, inferred
- 1 x Vaporizer (r_vaporizer_03, planner 0.3292, 8x6)
- 4 x Cooling Tower (r_cooling_tower_01, planner 3.9717, 50x50)  <- recipe not in recipes.json, inferred
- 1 x Lathe (r_lathe_03, planner 0.9085, 17x8)
- 2 x Blast Furnace MK2 (r_blast_furnace_MK2_04, planner 1.0599, 16x16)
- 1 x Paper Mill (r_paper_mill_02, planner 0.0155, 6x12)
- 2 x Advanced Coal Drill (r_advanced_coal_drill_01, planner 1.2400, 10x4)
- 11 x Ingot Molder (r_ingot_molder_03, planner 10.5992, 4x2)
- 8 x Electric Furnace (r_electric_furnace_06, planner 7.5709, 6x6)
- 5 x Blast Furnace (r_blast_furnace_13, planner 4.0378, 8x8)
- 1 x Advanced Assembler (r_advanced_assembler_13, planner 0.3100, 12x6)
- 1 x Quarry (r_quarry_02, planner 0.0413, 24x24)
- 1 x Roller (r_roller_02, planner 0.2480, 4x2)
- 1 x Press (r_press_02, planner 0.2480, 4x2)
- 1 x Ingot Molder (r_ingot_molder_03, planner 0.1240, 4x2)
- 1 x Electric Furnace (r_electric_furnace_02, planner 0.6200, 6x6)
- 2 x Iron Drill (r_iron_drill_01, planner 1.8600, 6x2)

## Warnings

## Assumptions / inferred data (check these!)
- r_coal_power_plant_01: not in recipes.json -> assumed machine m_coal_power_plant; ports inferred
- r_vertical_heat_exchanger_02: not in recipes.json -> assumed machine m_vertical_heat_exchanger; ports inferred
- r_modular_turbine_01: built modular turbine (input, 5 LPT, 1 IPT, 0 HPT, generator, output) = 118x12
- r_steam_condenser_01: not in recipes.json -> assumed machine m_steam_condenser; ports inferred
- r_mineshaft_drill_01: not in recipes.json -> assumed machine m_mineshaft_drill; ports inferred
- r_polisher_01: not in recipes.json -> assumed machine m_polisher; ports inferred
- r_tree_farm_01: built tree farm from guide layout = 64x36 (2 water tank(s), 1 output(s))
- r_air_separation_unit_01: not in recipes.json -> assumed machine m_air_separation_unit; ports inferred
- r_chemical_plant_15: not in recipes.json -> assumed machine m_chemical_plant; ports inferred
- r_cooling_tower_01: not in recipes.json -> assumed machine m_cooling_tower; ports inferred
    - r_coal_power_plant_01 input #0 (?, Item) -> m_coal_power_plant_port_6, m_coal_power_plant_port_7
    - r_coal_power_plant_01 input #1 (?, Fluid) -> m_coal_power_plant_port_5
    - r_coal_power_plant_01 output #0 (?, Fluid) -> m_coal_power_plant_port_3
    - r_coal_power_plant_01 output #1 (Exhaust, Fluid) -> m_coal_power_plant_port_4
    - r_vertical_heat_exchanger_02 input #0 (?, Fluid) -> m_vertical_heat_exchanger_port_3
    - r_vertical_heat_exchanger_02 input #1 (?, Fluid) -> m_vertical_heat_exchanger_port_4
    - r_vertical_heat_exchanger_02 output #0 (?, Fluid) -> m_vertical_heat_exchanger_port_1
    - r_vertical_heat_exchanger_02 output #1 (?, Fluid) -> m_vertical_heat_exchanger_port_2
    - r_steam_condenser_01 input #0 (Distilled Water, Fluid) -> m_steam_condenser_port_1, m_steam_condenser_port_2
    - r_steam_condenser_01 input #1 (?, Fluid) -> m_steam_condenser_port_3, m_steam_condenser_port_4
    - r_steam_condenser_01 output #0 (?, Fluid) -> m_steam_condenser_port_5
    - r_steam_condenser_01 output #1 (?, Fluid) -> m_steam_condenser_port_6, m_steam_condenser_port_7
    - r_mineshaft_drill_01 input #0 (Steel Drill Head, Item) -> m_mineshaft_drill_port_3, m_mineshaft_drill_port_4
    - r_mineshaft_drill_01 input #1 (?, Fluid) -> m_mineshaft_drill_port_1, m_mineshaft_drill_port_2
    - r_mineshaft_drill_01 output #0 (?, Item) -> m_mineshaft_drill_port_5, m_mineshaft_drill_port_6
    - r_mineshaft_drill_01 output #1 (?, Fluid) -> m_mineshaft_drill_port_9
    - r_mineshaft_drill_01 output #2 (Rock, Item) -> m_mineshaft_drill_port_7, m_mineshaft_drill_port_8
    - r_polisher_01 input #0 (?, Fluid) -> m_polisher_port_1
    - r_polisher_01 input #1 (?, Fluid) -> m_polisher_port_2
    - r_polisher_01 input #2 (Sodium Hydroxide Solution, Fluid) -> m_polisher_port_3
    - r_polisher_01 output #0 (?, Fluid) -> m_polisher_port_4
    - r_air_separation_unit_01 output #0 (?, Fluid) -> m_air_separation_unit_port_1
    - r_air_separation_unit_01 output #1 (?, Fluid) -> m_air_separation_unit_port_2
    - r_air_separation_unit_01 output #2 (Liquid Argon, Fluid) -> m_air_separation_unit_port_3
    - r_air_separation_unit_01 output #3 (?, Fluid) -> m_air_separation_unit_port_4
    - r_chemical_plant_15 input #0 (Chlorine, Fluid) -> m_chemical_plant_port_2
    - r_chemical_plant_15 input #1 (Hydrogen, Fluid) -> m_chemical_plant_port_3
    - r_chemical_plant_15 input #2 (?, Fluid) -> m_chemical_plant_port_4
    - r_chemical_plant_15 input #3 (Argon, Fluid) -> m_chemical_plant_port_5
    - r_chemical_plant_15 output #0 (?, Fluid) -> m_chemical_plant_port_8, m_chemical_plant_port_11, m_chemical_plant_port_12
    - r_cooling_tower_01 input #0 (?, Fluid) -> m_cooling_tower_port_2
    - r_cooling_tower_01 output #0 (Distilled Water, Fluid) -> m_cooling_tower_port_1
- net Exhaust (Fluid, large): flow unknown -> 1 pipe network(s); r_coal_power_plant_01 + r_exhaust_stack_01
- net ? (Fluid, large): flow unknown -> 8 pipe network(s); r_coal_power_plant_01 + r_vertical_heat_exchanger_02
- net ? (Fluid, large): flow unknown -> 8 pipe network(s); r_modular_turbine_01 + r_vertical_heat_exchanger_02
- net ? (Fluid, large): flow unknown -> 4 pipe network(s); r_modular_turbine_01 + r_steam_condenser_01
- net ? (Item): flow unknown -> 8 pipe network(s); r_coal_power_plant_01 + r_mineshaft_drill_01
- net ? (Fluid): flow unknown -> 4 pipe network(s); r_polisher_01 + r_steam_condenser_01
- net ? (Fluid, large): flow unknown -> 8 pipe network(s); r_coal_power_plant_01 + r_polisher_01
- net Distilled Water (Fluid): flow unknown -> 2 pipe network(s); r_atmospheric_distillation_plant_02 + r_cooling_tower_01 + r_steam_condenser_01
- net Steel Drill Head (Item): flow unknown -> 1 pipe network(s); r_lathe_03 + r_mineshaft_drill_01
- net ? (Fluid): flow unknown -> 1 pipe network(s); r_chemical_plant_15 + r_mineshaft_drill_01 + r_polisher_01
- net Sodium Hydroxide Solution (Fluid): flow unknown -> 8 pipe network(s); r_electrolysis_plant_02 + r_polisher_01
- net Concentrated Salt Solution (Fluid): 10.67/s -> 1 pipe network(s); r_atmospheric_distillation_plant_02 + r_electrolysis_plant_02
- net Water (Fluid): flow unknown -> 1 pipe network(s); r_atmospheric_distillation_plant_02 + r_electrolysis_plant_01 + r_tree_farm_01 + r_water_pump2_01
- net Coke Fuel (Item): 12.79/s -> 1 pipe network(s); r_blast_furnace_13 + r_blast_furnace_MK2_03 + r_blast_furnace_MK2_04
- net Oak Log (Item): flow unknown -> 1 pipe network(s); r_blast_furnace_MK2_03 + r_paper_mill_02 + r_tree_farm_01
- net Chlorine (Fluid): flow unknown -> 1 pipe network(s); r_chemical_plant_15 + r_electrolysis_plant_02 + r_paper_mill_02
- net Hydrogen (Fluid): flow unknown -> 1 pipe network(s); r_chemical_plant_15 + r_electrolysis_plant_01
- net ? (Fluid): flow unknown -> 1 pipe network(s); r_chemical_plant_15 + r_cooling_tower_01 + r_steam_condenser_01
- net Argon (Fluid): flow unknown -> 1 pipe network(s); r_chemical_plant_15 + r_vaporizer_03
- net Liquid Argon (Fluid): flow unknown -> 1 pipe network(s); r_air_separation_unit_01 + r_vaporizer_03
- net Steel Ingot (Item): 15.90/s -> 1 pipe network(s); r_blast_furnace_MK2_04 + r_lathe_03
- net Iron Ingot (Item): 5.30/s -> 1 pipe network(s); r_blast_furnace_MK2_04 + r_ingot_molder_03
- net Liquid Iron (Fluid): 10.60/s -> 1 pipe network(s); r_electric_furnace_06 + r_ingot_molder_03
- net Iron Mix (Item): 4.85/s -> 1 pipe network(s); r_blast_furnace_13 + r_electric_furnace_06
- net Rock (Item): flow unknown -> 5 pipe network(s); r_blast_furnace_13 + r_mineshaft_drill_01
- net Filter (Item): 0.06/s -> 1 pipe network(s); r_advanced_assembler_13 + r_exhaust_stack_01
- net Coal (Item): 0.31/s -> 1 pipe network(s); r_advanced_assembler_13 + r_advanced_coal_drill_01
- net Paper (Item): 0.12/s -> 1 pipe network(s); r_advanced_assembler_13 + r_paper_mill_02
- net Sand (Item): 0.12/s -> 1 pipe network(s); r_advanced_assembler_13 + r_quarry_02
- net Iron Coil (Item): 0.12/s -> 1 pipe network(s); r_advanced_assembler_13 + r_roller_02
- net Iron Plate (Item): 0.06/s -> 1 pipe network(s); r_press_02 + r_roller_02
- net Iron Ingot (Item): 0.06/s -> 1 pipe network(s); r_ingot_molder_03 + r_press_02
- net Liquid Iron (Fluid): 0.12/s -> 1 pipe network(s); r_electric_furnace_02 + r_ingot_molder_03
- net Raw Iron (Item): 0.12/s -> 1 pipe network(s); r_electric_furnace_02 + r_iron_drill_01
- self loop on r_vertical_heat_exchanger_02: output #0 -> input #1 uses same-machine (quantum) connection, only pipe stubs reserved
- self loop on r_blast_furnace_MK2_03: output #0 -> input #0 uses same-machine (quantum) connection, only pipe stubs reserved
- spacing rule: the 8 x m_mineshaft_drill must be at least 48 tiles apart (edge distance)

## Optimizer log
```
10 recipe(s) not in recipes.json, ports inferred (see report): r_coal_power_plant_01, r_vertical_heat_exchanger_02, r_modular_turbine_01, r_steam_condenser_01, r_mineshaft_drill_01, r_polisher_01, r_tree_farm_01, r_air_separation_unit_01, r_chemical_plant_15, r_cooling_tower_01
  module x3: 2x Coal Power Plant + 2x Vertical Heat Exchanger + 4x Modular Turbine (5 LPT, 0 HPT) + Steam Condenser + Mineshaft Drill + 2x Polisher + 10x Electrolysis Plant
  module x1: 2x Coal Power Plant + 2x Vertical Heat Exchanger + 4x Modular Turbine (5 LPT, 0 HPT) + Steam Condenser + Mineshaft Drill + 2x Polisher + 10x Electrolysis Plant + Blast Furnace
  module x1: Exhaust Stack + Mineshaft Drill + Tree Farm (88 trees) + 3x Blast Furnace MK2 + Lathe + Paper Mill + 2x Advanced Coal Drill + Blast Furnace + Advanced Assembler + Quarry + Roller + Press + Ingot Molder + Electric Furnace + 2x Iron Drill
  module x3: Mineshaft Drill + Blast Furnace
  module x2: Atmospheric Distillation Plant + 2x Cooling Tower
  module x1: Air Separation Unit + Chemical Plant + Vaporizer
Placement (15 blocks, 164 machines, 97 nets)...
  placement: 236928 iterations, bbox 280x397 = 111160 tiles, est. pipe length 13122
Attempt 1 (grow): time left 229s
    routing pass 1: 97 nets rerouted, 1878 overfull tiles, 1 unroutable (2.2s)
    routing pass 2: 78 nets rerouted, 1401 overfull tiles, 1 unroutable (2.7s)
    routing pass 3: 71 nets rerouted, 1184 overfull tiles, 1 unroutable (3.0s)
    routing pass 4: 66 nets rerouted, 1110 overfull tiles, 1 unroutable (3.2s)
    routing pass 5: 68 nets rerouted, 922 overfull tiles, 1 unroutable (2.9s)
    routing pass 6: 70 nets rerouted, 832 overfull tiles, 1 unroutable (4.2s)
    routing pass 7: 68 nets rerouted, 771 overfull tiles, 1 unroutable (3.7s)
    routing pass 8: 66 nets rerouted, 790 overfull tiles, 1 unroutable (4.3s)
    routing pass 9: 64 nets rerouted, 827 overfull tiles, 1 unroutable (4.9s)
    routing pass 10: 62 nets rerouted, 769 overfull tiles, 1 unroutable (4.6s)
    routing pass 11: 63 nets rerouted, 760 overfull tiles, 1 unroutable (4.5s)
    routing pass 12: 65 nets rerouted, 724 overfull tiles, 1 unroutable (4.0s)
    routing pass 13: 66 nets rerouted, 704 overfull tiles, 1 unroutable (4.3s)
    routing pass 14: 67 nets rerouted, 670 overfull tiles, 1 unroutable (4.0s)
    routing pass 15: 68 nets rerouted, 714 overfull tiles, 1 unroutable (5.2s)
    routing pass 16: 68 nets rerouted, 813 overfull tiles, 1 unroutable (4.6s)
    routing pass 17: 62 nets rerouted, 743 overfull tiles, 1 unroutable (5.5s)
    routing pass 18: 64 nets rerouted, 747 overfull tiles, 1 unroutable (5.2s)
    routing pass 19: 60 nets rerouted, 671 overfull tiles, 1 unroutable (5.6s)
  671 overfull tiles, 1 unrouted nets
  widening: 2x Coal Power Plant + 2x Verti:inner+1, Atmospheric Distillation Plant:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, 2x Coal Power Plant + 2x Verti:left+1, Mineshaft Drill + Blast Furnac:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, 2x Coal Power Plant + 2x Verti:left+2, Exhaust Stack + Mineshaft Dril:inner+1, r_electrolysis_plant_01:top+1, r_electrolysis_plant_01:right+2, 2x Coal Power Plant + 2x Verti:inner+1, 2x Coal Power Plant + 2x Verti:left+2, Mineshaft Drill + Blast Furnac:inner+1
Attempt 2 (grow): time left 151s
    routing pass 1: 97 nets rerouted, 858 overfull tiles, 0 unroutable (1.8s)
    routing pass 2: 73 nets rerouted, 655 overfull tiles, 0 unroutable (2.1s)
    routing pass 3: 70 nets rerouted, 433 overfull tiles, 0 unroutable (2.6s)
    routing pass 4: 66 nets rerouted, 332 overfull tiles, 0 unroutable (2.2s)
    routing pass 5: 63 nets rerouted, 315 overfull tiles, 0 unroutable (2.1s)
    routing pass 6: 60 nets rerouted, 274 overfull tiles, 0 unroutable (1.9s)
    routing pass 7: 52 nets rerouted, 244 overfull tiles, 0 unroutable (2.4s)
    routing pass 8: 54 nets rerouted, 188 overfull tiles, 0 unroutable (2.3s)
    routing pass 9: 51 nets rerouted, 163 overfull tiles, 0 unroutable (2.3s)
    routing pass 10: 49 nets rerouted, 138 overfull tiles, 0 unroutable (2.3s)
    routing pass 11: 48 nets rerouted, 176 overfull tiles, 0 unroutable (2.0s)
    routing pass 12: 44 nets rerouted, 144 overfull tiles, 0 unroutable (2.7s)
    routing pass 13: 44 nets rerouted, 167 overfull tiles, 0 unroutable (2.8s)
    routing pass 14: 41 nets rerouted, 149 overfull tiles, 0 unroutable (3.2s)
    routing pass 15: 37 nets rerouted, 126 overfull tiles, 0 unroutable (3.3s)
    routing pass 16: 34 nets rerouted, 155 overfull tiles, 0 unroutable (3.1s)
    routing pass 17: 32 nets rerouted, 149 overfull tiles, 0 unroutable (2.5s)
    routing pass 18: 32 nets rerouted, 92 overfull tiles, 0 unroutable (2.8s)
    routing pass 19: 31 nets rerouted, 120 overfull tiles, 0 unroutable (2.2s)
    routing pass 20: 31 nets rerouted, 89 overfull tiles, 0 unroutable (1.8s)
    routing pass 21: 30 nets rerouted, 92 overfull tiles, 0 unroutable (1.8s)
    routing pass 22: 29 nets rerouted, 142 overfull tiles, 0 unroutable (1.9s)
    routing pass 23: 28 nets rerouted, 60 overfull tiles, 0 unroutable (2.7s)
    routing pass 24: 28 nets rerouted, 91 overfull tiles, 0 unroutable (3.2s)
    routing pass 25: 27 nets rerouted, 119 overfull tiles, 0 unroutable (2.6s)
    routing pass 26: 26 nets rerouted, 76 overfull tiles, 0 unroutable (2.8s)
    routing pass 27: 30 nets rerouted, 74 overfull tiles, 0 unroutable (2.3s)
    routing pass 28: 25 nets rerouted, 86 overfull tiles, 0 unroutable (2.4s)
    routing pass 29: 28 nets rerouted, 62 overfull tiles, 3 unroutable (24.0s)
  62 overfull tiles, 3 unrouted nets
  widening: 2x Coal Power Plant + 2x Verti:inner+1, Atmospheric Distillation Plant:inner+1, Atmospheric Distillation Plant:bottom+1, Mineshaft Drill + Blast Furnac:inner+1, Exhaust Stack + Mineshaft Dril:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, 2x Coal Power Plant + 2x Verti:inner+1
Attempt 3 (grow): time left 55s
    routing pass 1: 97 nets rerouted, 694 overfull tiles, 0 unroutable (6.5s)
    routing pass 2: 69 nets rerouted, 561 overfull tiles, 0 unroutable (2.3s)
    routing pass 3: 69 nets rerouted, 369 overfull tiles, 0 unroutable (2.9s)
    routing pass 4: 59 nets rerouted, 295 overfull tiles, 0 unroutable (2.7s)
    routing pass 5: 55 nets rerouted, 251 overfull tiles, 0 unroutable (2.6s)
    routing pass 6: 48 nets rerouted, 219 overfull tiles, 0 unroutable (1.9s)
    routing pass 7: 46 nets rerouted, 173 overfull tiles, 0 unroutable (2.0s)
    routing pass 8: 48 nets rerouted, 171 overfull tiles, 0 unroutable (2.3s)
    routing pass 9: 49 nets rerouted, 153 overfull tiles, 0 unroutable (2.5s)
    routing pass 10: 40 nets rerouted, 139 overfull tiles, 0 unroutable (2.6s)
    routing pass 11: 38 nets rerouted, 129 overfull tiles, 0 unroutable (2.3s)
    routing pass 12: 40 nets rerouted, 147 overfull tiles, 0 unroutable (2.5s)
    routing pass 13: 37 nets rerouted, 88 overfull tiles, 0 unroutable (2.6s)
    routing pass 14: 33 nets rerouted, 101 overfull tiles, 0 unroutable (2.3s)
    routing pass 15: 32 nets rerouted, 102 overfull tiles, 0 unroutable (2.7s)
    routing pass 16: 32 nets rerouted, 100 overfull tiles, 0 unroutable (2.3s)
  100 overfull tiles, 0 unrouted nets
  widening: 2x Coal Power Plant + 2x Verti:inner+1, Atmospheric Distillation Plant:inner+1, 2x Coal Power Plant + 2x Verti:top+1, 2x Coal Power Plant + 2x Verti:left+1, 2x Coal Power Plant + 2x Verti:inner+1, Exhaust Stack + Mineshaft Dril:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, r_electrolysis_plant_01:right+1
Attempt 4 (grow): time left 12s
    routing pass 1: 97 nets rerouted, 629 overfull tiles, 0 unroutable (2.3s)
    routing pass 2: 69 nets rerouted, 516 overfull tiles, 0 unroutable (2.1s)
    routing pass 3: 67 nets rerouted, 274 overfull tiles, 0 unroutable (2.2s)
  274 overfull tiles, 0 unrouted nets
  widening: 2x Coal Power Plant + 2x Verti:inner+1, 2x Coal Power Plant + 2x Verti:right+1, r_electric_furnace_06:inner+1, r_electric_furnace_06:left+1, Atmospheric Distillation Plant:inner+1, Atmospheric Distillation Plant:bottom+1, 2x Coal Power Plant + 2x Verti:inner+1, Mineshaft Drill + Blast Furnac:inner+1, Exhaust Stack + Mineshaft Dril:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, Atmospheric Distillation Plant:inner+1, 2x Coal Power Plant + 2x Verti:inner+1, r_electrolysis_plant_01:top+1, r_electrolysis_plant_01:right+2, Mineshaft Drill + Blast Furnac:inner+1
Done in 295s
```