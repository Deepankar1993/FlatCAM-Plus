# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 6/10/2026                                          #
# MIT Licence                                              #
# ##########################################################

from appPreProcessor import PreProc


# This preprocessor is for GRBL 1.1 controllers (CNC 3018 and similar) fitted with a
# diode laser module that has air assist (e.g. 40W input / 5.5W optical output modules).
# The air assist pump/valve is expected to be wired to the coolant output of the
# controller board: it is turned ON with M8 at the start of the job and OFF with M9
# at the end of the job. Controllers without the coolant pin wired simply ignore M8/M9.


class GRBL_laser_air_assist(PreProc):

    include_header = True
    coordinate_format = "%.*f"
    feedrate_format = '%.*f'

    def start_code(self, p):
        units = ' ' + str(p['units']).lower()
        gcode = '(This preprocessor is used with a motion controller loaded with GRBL 1.1 firmware, )\n'
        gcode += '(for a LASER module with AIR ASSIST connected on the SPINDLE connector.)\n' \
                 '(The air assist is turned ON with M8 at job start and OFF with M9 at job end;)\n' \
                 '(wire the air assist pump/valve relay to the coolant - flood - output of the board.)\n' \
                 '(This preprocessor makes no moves on the Z axis, it will only move horizontally.)\n' \
                 '(The horizontal move is done with G0 - highest possible speed set in the GRBL controller.)\n' \
                 '(It assumes a manually focused laser.)\n' \
                 '(The laser is started with the M3 or M4 command and stopped with the M5 command.)\n' \
                 '(For variable power while moving - recommended for engraving - set the laser ON)\n' \
                 '(command to M4 and enable the GRBL laser mode: $32=1. The S value range is set)\n' \
                 '(by the GRBL $30 setting - usually 1000.)\n\n'

        xmin = '%.*f' % (p.coords_decimals, p['obj_options']['xmin'])
        xmax = '%.*f' % (p.coords_decimals, p['obj_options']['xmax'])
        ymin = '%.*f' % (p.coords_decimals, p['obj_options']['ymin'])
        ymax = '%.*f' % (p.coords_decimals, p['obj_options']['ymax'])

        gcode += '(Feedrate: ' + str(p['feedrate']) + units + '/min' + ')\n'
        gcode += '(Steps per circle: ' + str(p['steps_per_circle']) + ')\n'

        if str(p['obj_options']['type']) == 'Excellon' or str(p['obj_options']['type']) == 'Excellon Geometry':
            gcode += '(Preprocessor Excellon: ' + str(p['pp_excellon_name']) + ')\n'
        else:
            gcode += '(Preprocessor Geometry: ' + str(p['pp_geometry_name']) + ')\n' + '\n'

        gcode += '(X range: ' + '{: >9s}'.format(xmin) + ' ... ' + '{: >9s}'.format(xmax) + ' ' + units + ')\n'
        gcode += '(Y range: ' + '{: >9s}'.format(ymin) + ' ... ' + '{: >9s}'.format(ymax) + ' ' + units + ')\n\n'

        gcode += '(Laser Power - Spindle Speed: ' + str(p['spindlespeed']) + ')\n'
        gcode += '(Laser Minimum Power: ' + str(p['laser_min_power']) + ')\n\n'

        gcode += ('G20' if p.units.upper() == 'IN' else 'G21') + "\n"
        gcode += 'G90\n'
        gcode += 'G17\n'
        gcode += 'G94\n'
        gcode += 'M8 (air assist ON)'

        return gcode

    def startz_code(self, p):
        return ''

    def lift_code(self, p):
        if float(p.laser_min_power) > 0.0:
            # the formatted text: laser OFF must always be like this else the plotting will not be done correctly
            return '%s S%s (laser OFF)\n' % (str(p.laser_on_code), str(p.laser_min_power))
        else:
            return 'M5'

    def down_code(self, p):
        if p.spindlespeed:
            return '%s S%s' % (str(p.laser_on_code), str(p.spindlespeed))
        else:
            return str(p.laser_on_code)

    def toolchange_code(self, p):
        return ''

    def up_to_zero_code(self, p):
        return ''

    def position_code(self, p):
        # formula for skewing on x for example is:
        # x_fin = x_init + y_init/slope where slope = p._bed_limit_y / p._bed_skew_x (a.k.a tangent)
        if p._bed_skew_x == 0:
            x_pos = p.x + p._bed_offset_x
        else:
            x_pos = (p.x + p._bed_offset_x) + ((p.y / p._bed_limit_y) * p._bed_skew_x)

        if p._bed_skew_y == 0:
            y_pos = p.y + p._bed_offset_y
        else:
            y_pos = (p.y + p._bed_offset_y) + ((p.x / p._bed_limit_x) * p._bed_skew_y)

        return ('X' + self.coordinate_format + ' Y' + self.coordinate_format) % \
               (p.coords_decimals, x_pos, p.coords_decimals, y_pos)

    def rapid_code(self, p):
        return ('G0 ' + self.position_code(p)).format(**p)

    def linear_code(self, p):
        return ('G1 ' + self.position_code(p)).format(**p) + \
               ' F' + str(self.feedrate_format % (p.fr_decimals, p.feedrate))

    def end_code(self, p):
        coords_xy = p['xy_end']
        gcode = 'M9 (air assist OFF)\n'

        if coords_xy and coords_xy != '':
            gcode += 'G0 X{x} Y{y}'.format(x=coords_xy[0], y=coords_xy[1]) + "\n"
        return gcode

    def feedrate_code(self, p):
        return 'G1 F' + str(self.feedrate_format % (p.fr_decimals, p.feedrate))

    def z_feedrate_code(self, p):
        return 'G1 F' + str(self.feedrate_format % (p.fr_decimals, p.z_feedrate))

    def spindle_code(self, p):
        if p.spindlespeed:
            return '%s S%s' % (str(p.laser_on_code), str(p.spindlespeed))
        else:
            return str(p.laser_on_code)

    def dwell_code(self, p):
        return ''

    def spindle_stop_code(self, p):
        return 'M5'
