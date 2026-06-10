# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 6/11/2026                                          #
# MIT Licence                                              #
# ##########################################################

import os

from PyQt6 import QtWidgets, QtCore, QtGui
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    RadioSet, FCDoubleSpinner, FCSpinner, FCFileSaveDialog

from appPlugins import laser_core

import logging

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolLaser(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.decimals = self.app.decimals

        # Material presets
        self.presets = laser_core.load_laser_presets(
            os.path.join(self.app.app_home, 'assets', 'resources', 'laser_presets.json'))
        self.preset_by_name = {p['name']: p for p in self.presets}

        # the generated laser CNCJob object, used by the export button
        self.laser_cncjob = None

        # #############################################################################################################
        # ######################################## Tool GUI ###########################################################
        # #############################################################################################################
        self.ui = LaserUI(layout=self.layout, app=self.app, presets=self.presets)
        self.pluginName = self.ui.pluginName

        # #############################################################################################################
        # #####################################    Signals     ########################################################
        # #############################################################################################################
        self.connect_signals_at_init()

    def on_type_obj_index_changed(self, val):
        obj_type = 2 if val == 'geo' else 0
        self.ui.object_combo.setRootModelIndex(self.app.collection.index(obj_type, 0, QtCore.QModelIndex()))
        self.ui.object_combo.setCurrentIndex(0)
        self.ui.object_combo.obj_type = {
            "grb": "gerber", "geo": "geometry"
        }[val]

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolLaser()")

        if toggle:
            # if the splitter is hidden, display it
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

            # if the Tool Tab is hidden display it, else hide it but only if the objectName is the same
            found_idx = None
            for idx in range(self.app.ui.notebook.count()):
                if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                    found_idx = idx
                    break
            # show the Tab
            if not found_idx:
                try:
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                except RuntimeError:
                    self.app.ui.plugin_tab = QtWidgets.QWidget()
                    self.app.ui.plugin_tab.setObjectName("plugin_tab")
                    self.app.ui.plugin_tab_layout = QtWidgets.QVBoxLayout(self.app.ui.plugin_tab)
                    self.app.ui.plugin_tab_layout.setContentsMargins(2, 2, 2, 2)

                    self.app.ui.plugin_scroll_area = VerticalScrollArea()
                    self.app.ui.plugin_tab_layout.addWidget(self.app.ui.plugin_scroll_area)
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                # focus on Tool Tab
                self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

            try:
                if self.app.ui.plugin_scroll_area.widget().objectName() == self.pluginName and found_idx:
                    # if the Tool Tab is not focused, focus on it
                    if not self.app.ui.notebook.currentWidget() is self.app.ui.plugin_tab:
                        # focus on Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
                    else:
                        # else remove the Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)
                        self.app.ui.notebook.removeTab(2)

                        # if there are no objects loaded in the app then hide the Notebook widget
                        if not self.app.collection.get_list():
                            self.app.ui.splitter.setSizes([0, 1])
            except AttributeError:
                pass
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        super().run()

        self.set_tool_ui()

        self.app.ui.notebook.setTabText(2, _("Laser"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, **kwargs)

    def connect_signals_at_init(self):
        # #############################################################################
        # ############################ SIGNALS ########################################
        # #############################################################################
        self.ui.type_obj_radio.activated_custom.connect(self.on_type_obj_index_changed)
        self.ui.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.ui.power_source_radio.activated_custom.connect(self.on_power_source_changed)

        self.ui.generate_button.clicked.connect(self.on_generate)
        self.ui.export_button.clicked.connect(self.on_export)

        self.ui.reset_button.clicked.connect(self.set_tool_ui)

    def set_tool_ui(self):

        self.clear_ui(self.layout)
        self.ui = LaserUI(layout=self.layout, app=self.app, presets=self.presets)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        # parameters from the application defaults
        self.ui.power_entry.set_value(int(self.app.options["tools_laser_power_pct"]))
        self.ui.speed_entry.set_value(float(self.app.options["tools_laser_speed"]))
        self.ui.passes_entry.set_value(int(self.app.options["tools_laser_passes"]))
        self.ui.air_assist_cb.set_value(self.app.options["tools_laser_air_assist"])
        self.ui.mode_radio.set_value(self.app.options["tools_laser_mode"])

        # the preset; selecting it fills the parameters above unless it is 'Custom'
        self.ui.preset_combo.set_value(self.app.options["tools_laser_preset"])
        self.on_preset_changed()

        # power source; when the power is set in the sender (LaserGRBL) the Power entry is disabled
        power_source = 'app' if self.app.options["tools_laser_power_in_app"] else 'sender'
        self.ui.power_source_radio.set_value(power_source)
        self.on_power_source_changed(power_source)

        # select in the Source Object combobox the object that is selected in the Project Tab, if any
        obj = self.app.collection.get_active()
        if obj and obj.kind in ['gerber', 'geometry']:
            obj_type = {'gerber': 'grb', 'geometry': 'geo'}[obj.kind]
            self.ui.type_obj_radio.set_value(obj_type)
            # run once to update the obj_type attribute in the FCCombobox so the last object is showed in cb
            self.on_type_obj_index_changed(val=obj_type)
            self.ui.object_combo.set_value(obj.obj_options['name'])
        else:
            self.ui.type_obj_radio.set_value('grb')
            # run once to update the obj_type attribute in the FCCombobox so the last object is showed in cb
            self.on_type_obj_index_changed(val='grb')

    def on_preset_changed(self, index=None):
        """Fill the laser parameters from the selected material preset.
        Selecting 'Custom' changes nothing."""
        preset_name = self.ui.preset_combo.get_value()
        preset = self.preset_by_name.get(preset_name)
        if preset is None or preset_name == 'Custom':
            return

        self.ui.power_entry.set_value(int(preset['power_pct']))
        self.ui.speed_entry.set_value(float(preset['speed']))
        self.ui.passes_entry.set_value(int(preset['passes']))
        self.ui.air_assist_cb.set_value(bool(preset['air_assist']))
        self.ui.mode_radio.set_value(preset['laser_mode'])

    def on_power_source_changed(self, val):
        """When the power is set in the sender (LaserGRBL), the Power entry is greyed out."""
        self.ui.power_entry.setDisabled(val == 'sender')

    def _resolve_geometry(self, source_obj):
        """Return a GeometryObject to trace. For a Gerber source create an internal
        'follow' geometry (the centerline of the Gerber traces)."""
        if source_obj.kind == 'geometry':
            return source_obj

        if source_obj.kind == 'gerber':
            trace_name = '%s_laser_trace' % source_obj.obj_options['name']

            # follow_geo() -> app_obj.new_object() runs synchronously when called from the
            # main thread (the object_created signal is delivered directly), so the new
            # object is in the collection when the call returns. The collection may rename
            # it on a name collision, therefore detect it by diffing the collection names.
            names_before = set(self.app.collection.get_names())
            source_obj.follow_geo(outname=trace_name)

            geo = None
            for new_name in set(self.app.collection.get_names()) - names_before:
                candidate = self.app.collection.get_by_name(new_name)
                if candidate is not None and candidate.kind == 'geometry':
                    geo = candidate
                    break

            if geo is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Could not create the laser trace geometry."))
            return geo

        self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a Gerber or Geometry object."))
        return None

    def on_generate(self):
        """Generate a CNCJob object with laser G-code from the selected source object."""
        obj_name = self.ui.object_combo.currentText()
        source_obj = self.app.collection.get_by_name(obj_name)
        if source_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), str(obj_name)))
            return

        geo = self._resolve_geometry(source_obj)
        if geo is None:
            return

        # laser parameters from the UI
        power_in_app = self.ui.power_source_radio.get_value() == 'app'
        power_pct = self.ui.power_entry.get_value()
        speed = self.ui.speed_entry.get_value()
        n_passes = int(self.ui.passes_entry.get_value())
        air_assist = self.ui.air_assist_cb.get_value()
        laser_mode = self.ui.mode_radio.get_value()

        params = {
            'power_in_app': power_in_app,
            'power_pct': power_pct,
            'power_max': float(self.app.options['tools_laser_power_max']),
            'speed': speed,
            'air_assist': air_assist,
            'laser_mode': laser_mode,
        }

        tools_dict = laser_core.build_laser_tools_dict(geo.obj_options, params, geo.solid_geometry)

        # adapt the dict to what the milling engine reads
        for tool_uid in tools_dict:
            tool_data = tools_dict[tool_uid]['data']
            # the engine takes the tool diameter from the data dict
            tool_data['tools_mill_tooldia'] = laser_core.LASER_MARKER_DIA
            # the engine expects a number here (the empty string used as the 'power set in
            # the sender' marker would raise in float()/int()); a 0 value makes the laser
            # preprocessors emit a bare M3/M4 so LaserGRBL controls the power
            if tool_data['tools_mill_spindlespeed'] == '':
                tool_data['tools_mill_spindlespeed'] = 0

        out_name = '%s_laser' % source_obj.obj_options['name']

        # Generate the CNCJob with the same engine the Milling plugin uses; unlike the
        # legacy GeometryObject.mtool_gen_cncjob() it forwards the laser parameters
        # (tools_mill_laser_on, tools_mill_min_power) to the G-code generator.
        # With use_thread=False it runs synchronously on the main thread, so the new
        # object is in the collection when the call returns; the collection may rename
        # it on a name collision, therefore detect it by diffing the collection names.
        names_before = set(self.app.collection.get_names())
        self.app.milling_tool.generate_cnc_job_handler(
            geo_obj=geo, outname=out_name, tools_dict=tools_dict,
            toolchange=False, plot=True, use_thread=False, from_tcl=True)

        cncjob = None
        for new_name in set(self.app.collection.get_names()) - names_before:
            candidate = self.app.collection.get_by_name(new_name)
            if candidate is not None and candidate.kind == 'cncjob':
                cncjob = candidate
                break

        if cncjob is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Laser job generation failed."))
            return

        # the milling engine switches to the Properties tab; come back to this plugin
        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

        # multiple passes: repeat the cut body (laser ON .. laser OFF) of each tool G-code
        if n_passes > 1:
            repeated_any = False
            for tool_uid in cncjob.tools:
                new_gcode, ok = laser_core.repeat_cut_passes(cncjob.tools[tool_uid]['gcode'], n_passes)
                if ok:
                    cncjob.tools[tool_uid]['gcode'] = new_gcode
                    repeated_any = True
            if not repeated_any:
                self.app.inform.emit(
                    '[WARNING_NOTCL] %s' % _("Could not apply multiple passes; generated a single pass. "
                                             "You can set passes in LaserGRBL instead."))

        # The export - and the CNCJob object's own 'Save CNC Code' button - write
        # cncjob.source_file, so rebuild it from the per-tool G-code. This propagates the
        # repeated passes and also makes sure the start G-code is included (the
        # multi-geometry engine path leaves it out of source_file).
        total_gcode = ''
        for tool_uid in cncjob.tools:
            total_gcode += cncjob.tools[tool_uid]['gcode']
        cncjob.source_file = cncjob.gc_start + total_gcode

        self.laser_cncjob = cncjob

        # remember the used parameters
        self.app.options['tools_laser_power_pct'] = power_pct
        self.app.options['tools_laser_speed'] = speed
        self.app.options['tools_laser_passes'] = n_passes
        self.app.options['tools_laser_air_assist'] = air_assist
        self.app.options['tools_laser_mode'] = laser_mode
        self.app.options['tools_laser_power_in_app'] = power_in_app
        self.app.options['tools_laser_preset'] = self.ui.preset_combo.get_value()

        self.app.inform.emit('[success] %s' % _("Laser job generated. Use 'Export for LaserGRBL'."))

    def on_export(self):
        """Save the laser job G-code to a file that can be loaded in LaserGRBL."""
        if self.laser_cncjob is None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Generate a laser job first."))
            return

        obj_name = self.laser_cncjob.obj_options['name']
        last_folder = self.app.options['tools_laser_last_export_folder']
        if not last_folder or not os.path.isdir(last_folder):
            last_folder = self.app.get_last_save_folder()

        _filter_ = "G-Code Files (*.nc *.gcode *.ngc);;All Files (*.*)"
        try:
            dir_file_to_save = last_folder + '/' + str(obj_name) + '.nc'
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Export for LaserGRBL"),
                directory=dir_file_to_save,
                ext_filter=_filter_
            )
        except TypeError:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Export for LaserGRBL"),
                ext_filter=_filter_
            )

        if str(filename) == '':
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Export cancelled ..."))
            return

        self._export_to_file(filename)

    def _export_to_file(self, filename):
        """Write the generated laser job G-code to the given file, through the same
        handler used by the CNCJob object's 'Save CNC Code' button."""
        filename = str(filename)
        ret_val = self.laser_cncjob.export_gcode_handler(filename, is_gcode=True, rename_object=False)
        if ret_val == 'fail':
            return 'fail'

        # remember the folder for the next export
        self.app.options['tools_laser_last_export_folder'] = os.path.dirname(filename)


class LaserUI:

    pluginName = _("Laser")

    def __init__(self, layout, app, presets):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout
        self.presets = presets

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(
            _("Generate a GRBL laser job from a Gerber or Geometry object.")
        )
        self.tools_box.addWidget(title_label)

        # #############################################################################################################
        # Source Object Frame
        # #############################################################################################################
        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            _("The object whose geometry will be traced by the laser.")
        )
        self.tools_box.addWidget(self.obj_combo_label)

        obj_frame = FCFrame()
        self.tools_box.addWidget(obj_frame)

        obj_grid = GLay(v_spacing=5, h_spacing=3)
        obj_frame.setLayout(obj_grid)

        # Type of object used as the source for the laser job
        self.type_obj_radio = RadioSet([{'label': _('Gerber'), 'value': 'grb'},
                                        {'label': _('Geometry'), 'value': 'geo'}])

        self.type_obj_radio_label = FCLabel('%s:' % _("Type"))
        self.type_obj_radio_label.setToolTip(
            _("Specify the type of object used as source for the laser job.\n"
              "The object can be of type: Gerber or Geometry.\n"
              "The selection here decide the type of objects that will be\n"
              "in the Source Object combobox.")
        )
        obj_grid.addWidget(self.type_obj_radio_label, 0, 0)
        obj_grid.addWidget(self.type_obj_radio, 0, 1)

        # List of objects that can be the source of the laser job
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.object_combo.is_last = True

        obj_grid.addWidget(self.object_combo, 2, 0, 1, 2)

        # #############################################################################################################
        # Parameters Frame
        # #############################################################################################################
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(
            _("Laser engraving/cutting parameters.")
        )
        self.tools_box.addWidget(self.param_label)

        param_frame = FCFrame()
        self.tools_box.addWidget(param_frame)

        param_grid = GLay(v_spacing=5, h_spacing=3)
        param_frame.setLayout(param_grid)

        # Material preset
        self.preset_label = FCLabel('%s:' % _("Material preset"))
        self.preset_label.setToolTip(
            _("A set of laser parameters suited for a certain material.\n"
              "Selecting a preset will fill the parameters below.\n"
              "Select 'Custom' to set the parameters manually.")
        )
        self.preset_combo = FCComboBox()
        self.preset_combo.addItems([p['name'] for p in self.presets])

        param_grid.addWidget(self.preset_label, 0, 0)
        param_grid.addWidget(self.preset_combo, 0, 1)

        # Power source
        self.power_source_label = FCLabel('%s:' % _("Power source"))
        self.power_source_label.setToolTip(
            _("Where the laser power is set:\n"
              "- 'Set in FlatCAM' -> the power below is written in the G-code\n"
              "- 'Set in LaserGRBL' -> the G-code has no power value so the\n"
              "sender application (LaserGRBL) controls the power.")
        )
        self.power_source_radio = RadioSet([{'label': _('Set in FlatCAM'), 'value': 'app'},
                                            {'label': _('Set in LaserGRBL'), 'value': 'sender'}])

        param_grid.addWidget(self.power_source_label, 2, 0)
        param_grid.addWidget(self.power_source_radio, 2, 1)

        # Power
        self.power_label = FCLabel('%s:' % _("Power"))
        self.power_label.setToolTip(
            _("Laser power as a percentage of the maximum power.")
        )
        self.power_entry = FCSpinner(suffix='%', callback=self.confirmation_message_int)
        self.power_entry.set_range(0, 100)

        param_grid.addWidget(self.power_label, 4, 0)
        param_grid.addWidget(self.power_entry, 4, 1)

        # Speed
        speed_unit = _("mm/min") if str(self.app.app_units).upper() == 'MM' else _("in/min")
        self.speed_label = FCLabel('%s:' % _("Speed"))
        self.speed_label.setToolTip(
            '%s\n%s.' % (_("The speed of the laser head while the laser is on,"), speed_unit)
        )
        self.speed_entry = FCDoubleSpinner(suffix=speed_unit, callback=self.confirmation_message)
        self.speed_entry.set_range(1.0000, 100000.0000)
        self.speed_entry.set_precision(self.decimals)
        self.speed_entry.setSingleStep(10)

        param_grid.addWidget(self.speed_label, 6, 0)
        param_grid.addWidget(self.speed_entry, 6, 1)

        # Passes
        self.passes_label = FCLabel('%s:' % _("Passes"))
        self.passes_label.setToolTip(
            _("How many times the laser job is repeated.\n"
              "Useful to cut through thicker materials.")
        )
        self.passes_entry = FCSpinner(callback=self.confirmation_message_int)
        self.passes_entry.set_range(1, 100)

        param_grid.addWidget(self.passes_label, 8, 0)
        param_grid.addWidget(self.passes_entry, 8, 1)

        # Air assist
        self.air_assist_cb = FCCheckBox('%s' % _("Air assist"))
        self.air_assist_cb.setToolTip(
            _("When checked, the air assist pump is turned on\n"
              "for the duration of the job.")
        )
        param_grid.addWidget(self.air_assist_cb, 10, 0, 1, 2)

        # Laser mode
        self.mode_label = FCLabel('%s:' % _("Laser mode"))
        self.mode_label.setToolTip(
            _("Laser power mode:\n"
              "- 'Dynamic (M4)' -> power is adjusted with the speed; best for engraving\n"
              "- 'Constant (M3)' -> constant power; best for cutting.")
        )
        self.mode_radio = RadioSet([{'label': _('Dynamic (M4)'), 'value': 'M4'},
                                    {'label': _('Constant (M3)'), 'value': 'M3'}])

        param_grid.addWidget(self.mode_label, 12, 0)
        param_grid.addWidget(self.mode_radio, 12, 1)

        GLay.set_common_column_size([obj_grid, param_grid], 0)

        # #############################################################################################################
        # Buttons
        # #############################################################################################################
        self.generate_button = FCButton(_("Generate Laser Job"), bold=True)
        self.generate_button.setIcon(QtGui.QIcon(self.app.resource_location + '/cnc32.png'))
        self.generate_button.setToolTip(
            _("Generate a CNCJob object with laser G-code\n"
              "made using the parameters above.")
        )
        self.tools_box.addWidget(self.generate_button)

        self.export_button = FCButton(_("Export for LaserGRBL"), bold=True)
        self.export_button.setIcon(QtGui.QIcon(self.app.resource_location + '/save_as.png'))
        self.export_button.setToolTip(
            _("Save the generated laser G-code to a file\n"
              "that can be loaded in LaserGRBL.")
        )
        self.tools_box.addWidget(self.export_button)

        self.layout.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.layout.addWidget(self.reset_button)

    def confirmation_message(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%.*f, %.*f]' % (_("Edited value is out of range"),
                                                                                  self.decimals,
                                                                                  minval,
                                                                                  self.decimals,
                                                                                  maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

    def confirmation_message_int(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%d, %d]' %
                                            (_("Edited value is out of range"), minval, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)
