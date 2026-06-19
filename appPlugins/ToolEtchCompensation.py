# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 2/14/2020                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCEntry, \
    RadioSet, FCDoubleSpinner, NumericalEvalEntry
from camlib import flatten_shapely_geometry

import logging
from copy import deepcopy
import math

from shapely.ops import unary_union

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolEtchCompensation(AppTool):
    plugin_tooltip = _("Grow or shrink Gerber copper to compensate for chemical etching undercut.")

    def __init__(self, app):
        self.app = app
        self.decimals = self.app.decimals

        AppTool.__init__(self, app)

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = EtchUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='', **kwargs)

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolEtchCompensation()")
        self.app.log.debug("ToolEtchCompensation() is running ...")

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

        self.app.ui.notebook.setTabText(2, _("Etch Compensation"))

    def connect_signals_at_init(self):
        self.ui.compensate_btn.clicked.connect(self.on_compensate)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)
        self.ui.ratio_radio.activated_custom.connect(self.on_ratio_change)

        self.ui.oz_entry.textChanged.connect(self.on_oz_conversion)
        self.ui.mils_entry.textChanged.connect(self.on_mils_conversion)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = EtchUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self.ui.thick_entry.set_value(18.0)
        self.ui.ratio_radio.set_value('factor')

        # SELECT THE CURRENT OBJECT
        obj = self.app.collection.get_active()
        if obj and obj.kind == 'gerber':
            obj_name = obj.obj_options['name']
            self.ui.gerber_combo.set_value(obj_name)

    def on_ratio_change(self, val):
        """
        Called on activated_custom signal of the RadioSet GUI element self.radio_ratio

        :param val:     'c' or 'p': 'c' means custom factor and 'p' means preselected etchants
        :type val:      str
        :return:        None
        :rtype:
        """
        if val == 'factor':
            self.ui.etchants_label.hide()
            self.ui.etchants_combo.hide()
            self.ui.factor_label.show()
            self.ui.factor_entry.show()
            self.ui.offset_label.hide()
            self.ui.offset_entry.hide()
        elif val == 'etch_list':
            self.ui.etchants_label.show()
            self.ui.etchants_combo.show()
            self.ui.factor_label.hide()
            self.ui.factor_entry.hide()
            self.ui.offset_label.hide()
            self.ui.offset_entry.hide()
        else:
            self.ui.etchants_label.hide()
            self.ui.etchants_combo.hide()
            self.ui.factor_label.hide()
            self.ui.factor_entry.hide()
            self.ui.offset_label.show()
            self.ui.offset_entry.show()

    def on_oz_conversion(self, txt):
        try:
            val = eval(txt)
            # oz thickness to mils by multiplying with 1.37
            # mils to microns by multiplying with 25.4
            val *= 34.798
        except Exception:
            self.ui.oz_to_um_entry.set_value('')
            return
        self.ui.oz_to_um_entry.set_value(val, self.decimals)

    def on_mils_conversion(self, txt):
        try:
            val = eval(txt)
            val *= 25.4
        except Exception:
            self.ui.mils_to_um_entry.set_value('')
            return
        self.ui.mils_to_um_entry.set_value(val, self.decimals)

    def on_compensate(self):
        self.app.log.debug("ToolEtchCompensation.on_compensate()")

        ratio_type = self.ui.ratio_radio.get_value()
        thickness = self.ui.thick_entry.get_value() / 1000     # in microns

        grb_circle_steps = int(self.app.options["gerber_circle_steps"])
        obj_name = self.ui.gerber_combo.currentText()

        outname = obj_name + "_comp"

        # Get source object.
        try:
            grb_obj = self.app.collection.get_by_name(obj_name)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(obj_name)))
            return "Could not retrieve object: %s with error: %s" % (obj_name, str(e))

        if grb_obj is None:
            if obj_name == '':
                obj_name = 'None'
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), str(obj_name)))
            return

        if ratio_type == 'factor':
            factor_value = self.ui.factor_entry.get_value()
            if factor_value is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Missing parameter value."))
                return
            if factor_value <= 0:
                # etch_factor = 1 / factor_value -> a value of 0 crashed with ZeroDivisionError,
                # and a negative value silently shrank the copper instead of growing it. The Etch
                # Factor (depth-to-lateral etch ratio) is always a positive, non-zero number.
                self.app.inform.emit(
                    '[ERROR_NOTCL] %s' % _("The Etch Factor must be a positive, non-zero number."))
                return
            etch_factor = 1 / factor_value
            offset = thickness / etch_factor
        elif ratio_type == 'etch_list':
            etchant = self.ui.etchants_combo.get_value()
            if etchant == "CuCl2":
                etch_factor = 0.33
            else:
                etch_factor = 0.25
            offset = thickness / etch_factor
        else:
            offset_value = self.ui.offset_entry.get_value()
            if offset_value is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Missing parameter value."))
                return
            offset = offset_value / 1000   # in microns

        if offset == 0:
            # no need to do anything for zero value, offset, isn't it?
            # compensating with zero is the same as the original
            return

        grb_obj.solid_geometry = flatten_shapely_geometry(grb_obj.solid_geometry)

        # an object with no geometry would silently produce an empty result, so bail out with a clear message
        if not grb_obj.solid_geometry:
            self.app.inform.emit(
                '[ERROR_NOTCL] %s' % _("The source object has no geometry to compensate."))
            return

        new_solid_geometry = []
        for poly in grb_obj.solid_geometry:
            # only polygonal/linear geometry can be buffered; skip anything empty or invalid
            if poly is None or poly.is_empty:
                continue
            new_solid_geometry.append(poly.buffer(offset, int(grb_circle_steps)))

        if not new_solid_geometry:
            self.app.inform.emit(
                '[ERROR_NOTCL] %s' % _("The source object has no geometry to compensate."))
            return
        new_solid_geometry = unary_union(new_solid_geometry)

        new_options = {}
        for opt in grb_obj.obj_options:
            new_options[opt] = deepcopy(grb_obj.obj_options[opt])

        new_apertures = deepcopy(grb_obj.tools)

        # update the apertures attributes (keys in the apertures dict)
        for ap in new_apertures:
            # some apertures (e.g. macro-based or malformed) may not declare a 'type'; treat them as generic
            ap_type = new_apertures[ap].get('type', None)
            for k in new_apertures[ap]:
                if ap_type == 'R' or ap_type == 'O':
                    if k == 'width' or k == 'height':
                        new_apertures[ap][k] += offset
                else:
                    if k == 'size' or k == 'width' or k == 'height':
                        new_apertures[ap][k] += offset

                if k == 'geometry':
                    for geo_el in new_apertures[ap][k]:
                        # 'solid' may be missing, None, or an empty geometry; only buffer real shapes
                        solid = geo_el.get('solid', None) if isinstance(geo_el, dict) else None
                        if solid is not None and not solid.is_empty:
                            geo_el['solid'] = solid.buffer(offset, int(grb_circle_steps))

        # in case of 'R' or 'O' aperture type we need to update the aperture 'size' after
        # the 'width' and 'height' keys were updated
        for ap in new_apertures:
            ap_type = new_apertures[ap].get('type', None)
            if ap_type != 'R' and ap_type != 'O':
                continue
            # 'width'/'height' may be absent on a malformed aperture; only recompute 'size' when both exist
            if 'size' in new_apertures[ap] and \
                    'width' in new_apertures[ap] and 'height' in new_apertures[ap]:
                new_apertures[ap]['size'] = math.sqrt(
                    new_apertures[ap]['width'] ** 2 + new_apertures[ap]['height'] ** 2)

        def init_func(new_obj, app_obj):
            """
            Init a new object in FlatCAM Object collection

            :param new_obj:     New object
            :type new_obj:      ObjectCollection
            :param app_obj:     App
            :type app_obj:      appMain.App
            :return:            None
            :rtype:
            """
            new_obj.obj_options.update(new_options)
            new_obj.obj_options['name'] = outname
            new_obj.fill_color = deepcopy(grb_obj.fill_color)
            new_obj.outline_color = deepcopy(grb_obj.outline_color)

            new_obj.tools = deepcopy(new_apertures)

            new_obj.solid_geometry = deepcopy(new_solid_geometry)
            new_obj.source_file = app_obj.f_handlers.export_gerber(obj_name=outname, filename=None, local_use=new_obj,
                                                                   use_thread=False)

        self.app.app_obj.new_object('gerber', outname, init_func)

    def reset_fields(self):
        self.ui.gerber_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))

    @staticmethod
    def poly2rings(poly):
        return [poly.exterior] + [interior for interior in poly.interiors]


class EtchUI:

    pluginName = _("Etch Compensation")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        # Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.tools_box.addWidget(title_label)

        # Plain-language description for beginners
        self.description_label = FCLabel(
            _("When a PCB is wet-etched, the etchant eats sideways under the mask, so the finished\n"
              "copper ends up narrower than your design. This tool grows every copper feature by that\n"
              "lateral undercut, so the etched board matches the original artwork. Use it before\n"
              "generating Gerber output for boards you intend to etch yourself.")
        )
        self.description_label.setWordWrap(True)
        self.tools_box.addWidget(self.description_label)

        # #############################################################################################################
        # Source Object Frame
        # #############################################################################################################
        self.gerber_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.gerber_label.setToolTip(
            _("The Gerber object to compensate.\n"
              "Pick the copper layer you are going to etch (for example a top or bottom\n"
              "copper Gerber). A new object named '<source>_comp' with grown copper\n"
              "features will be created; the original is left unchanged.")
        )
        self.tools_box.addWidget(self.gerber_label)

        # Target Gerber Object
        self.gerber_combo = FCComboBox()
        self.gerber_combo.setModel(self.app.collection)
        self.gerber_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.gerber_combo.is_last = True
        self.gerber_combo.obj_type = "Gerber"

        self.tools_box.addWidget(self.gerber_combo)

        # #############################################################################################################
        # Utilities
        # #############################################################################################################
        self.util_label = FCLabel('%s' % _("Utilities"), color='red', bold=True)
        self.util_label.setToolTip(
            _("Optional helpers to work out the Copper Thickness in microns.\n"
              "Copper weight is often given in ounces (oz) or thickness in mils, but this\n"
              "tool expects microns [um]. Use these converters if you only know the oz or\n"
              "mils value.")
        )
        self.tools_box.addWidget(self.util_label)

        util_frame = FCFrame()
        self.tools_box.addWidget(util_frame)

        # Grid Layout
        grid0 = GLay(v_spacing=5, h_spacing=3)
        util_frame.setLayout(grid0)

        # Oz to um conversion
        self.oz_um_label = FCLabel('%s:' % _('Oz to Microns'))
        self.oz_um_label.setToolTip(
            _("Convert copper weight in ounces (oz) to thickness in microns [um].\n"
              "Typical PCB copper is 1 oz, which is about 35 um; 2 oz is about 70 um.\n"
              "You can type a formula using the operators: /, *, +, -, % .\n"
              "Use the dot as the decimal separator.")
        )
        grid0.addWidget(self.oz_um_label, 0, 0, 1, 2)

        hlay_1 = QtWidgets.QHBoxLayout()

        self.oz_entry = NumericalEvalEntry(border_color='#0069A9')
        self.oz_entry.setPlaceholderText(_("Oz value"))
        self.oz_entry.setToolTip(
            _("Copper weight in ounces (oz). For example enter 1 for standard 1 oz copper.")
        )
        self.oz_to_um_entry = FCEntry()
        self.oz_to_um_entry.setPlaceholderText(_("Microns value"))
        self.oz_to_um_entry.setReadOnly(True)
        self.oz_to_um_entry.setToolTip(
            _("Result of the conversion, in microns [um]. Copy this into Copper Thickness.")
        )

        hlay_1.addWidget(self.oz_entry)
        hlay_1.addWidget(FCLabel(" "))
        hlay_1.addWidget(self.oz_to_um_entry)
        grid0.addLayout(hlay_1, 2, 0, 1, 2)

        # Mils to um conversion
        self.mils_um_label = FCLabel('%s:' % _('Mils to Microns'))
        self.mils_um_label.setToolTip(
            _("Convert a thickness in mils (thousandths of an inch) to microns [um].\n"
              "1 mil equals 25.4 um, so 1.4 mils is about 35 um (roughly 1 oz copper).\n"
              "You can type a formula using the operators: /, *, +, -, % .\n"
              "Use the dot as the decimal separator.")
        )
        grid0.addWidget(self.mils_um_label, 4, 0, 1, 2)

        hlay_2 = QtWidgets.QHBoxLayout()

        self.mils_entry = NumericalEvalEntry(border_color='#0069A9')
        self.mils_entry.setPlaceholderText(_("Mils value"))
        self.mils_entry.setToolTip(
            _("Thickness in mils (thousandths of an inch). For example enter 1.4 for 1 oz copper.")
        )
        self.mils_to_um_entry = FCEntry()
        self.mils_to_um_entry.setPlaceholderText(_("Microns value"))
        self.mils_to_um_entry.setReadOnly(True)
        self.mils_to_um_entry.setToolTip(
            _("Result of the conversion, in microns [um]. Copy this into Copper Thickness.")
        )

        hlay_2.addWidget(self.mils_entry)
        hlay_2.addWidget(FCLabel(" "))
        hlay_2.addWidget(self.mils_to_um_entry)
        grid0.addLayout(hlay_2, 6, 0, 1, 2)

        # #############################################################################################################
        # COMMON PARAMETERS Frame
        # #############################################################################################################
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(_("Parameters used for this tool."))
        self.tools_box.addWidget(self.param_label)

        self.gp_frame = FCFrame()
        self.tools_box.addWidget(self.gp_frame)

        grid1 = GLay(v_spacing=5, h_spacing=3)
        self.gp_frame.setLayout(grid1)

        # Thickness
        self.thick_label = FCLabel('%s:' % _('Copper Thickness'))
        self.thick_label.setToolTip(
            _("How thick the copper foil is, in microns [um].\n"
              "The thicker the copper, the more it is undercut sideways during etching.\n"
              "Typical values: 1 oz copper = 35 um, 2 oz copper = 70 um.\n"
              "If you only know oz or mils, use the converters in the Utilities section above.")
        )
        self.thick_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.thick_entry.set_precision(self.decimals)
        self.thick_entry.set_range(0.0000, 10000.0000)

        grid1.addWidget(self.thick_label, 0, 0)
        grid1.addWidget(self.thick_entry, 0, 1)

        self.ratio_label = FCLabel('%s:' % _("Ratio"))
        self.ratio_label.setToolTip(
            _("How to decide how much to grow the copper. Choose one method:\n"
              "- Etch Factor: you type the depth-to-side etch ratio yourself.\n"
              "- Etchants list: pick your chemical and a typical ratio is used for you.\n"
              "- Manual offset: you give the exact amount to grow, in microns, directly.\n"
              "If you are unsure, start with the Etchants list.")
        )
        self.ratio_radio = RadioSet([
            {'label': _('Etch Factor'), 'value': 'factor'},
            {'label': _('Etchants list'), 'value': 'etch_list'},
            {'label': _('Manual offset'), 'value': 'manual'}
        ], orientation='vertical', compact=True)
        self.ratio_radio.setToolTip(
            _("Pick how the copper growth is calculated. The matching input field below\n"
              "(Etch Factor, Etchants, or Offset) will appear once you select an option.")
        )

        grid1.addWidget(self.ratio_label, 2, 0, 1, 2)
        grid1.addWidget(self.ratio_radio, 4, 0, 1, 2)

        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        grid1.addWidget(separator_line, 6, 0, 1, 2)

        # Etchants
        self.etchants_label = FCLabel('%s:' % _('Etchants'))
        self.etchants_label.setToolTip(
            _("The chemical you will use to etch the board.\n"
              "Each etchant undercuts the copper a bit differently, so picking one sets a\n"
              "typical etch factor for you automatically (no need to know the number):\n"
              "- CuCl2 (copper chloride): etch factor about 3.\n"
              "- Fe3Cl (ferric chloride) and alkaline baths: etch factor about 4.")
        )
        self.etchants_combo = FCComboBox(callback=self.confirmation_message)
        self.etchants_combo.addItems(["CuCl2", "Fe3Cl", _("Alkaline baths")])
        self.etchants_combo.setToolTip(
            _("Choose the etchant you will use. A typical etch factor for that\n"
              "chemical is applied automatically.")
        )

        grid1.addWidget(self.etchants_label, 8, 0)
        grid1.addWidget(self.etchants_combo, 8, 1)

        # Etch Factor
        self.factor_label = FCLabel('%s:' % _('Etch Factor'))
        self.factor_label.setToolTip(
            _("The depth-to-side etch ratio: how much the etchant cuts down for every\n"
              "unit it cuts sideways. A higher number means less sideways undercut, so\n"
              "less compensation is needed.\n"
              "Typical values are between 2 and 3. Must be a positive, non-zero number.\n"
              "You may type a formula using the operators: /, *, +, -, % .")
        )
        self.factor_entry = NumericalEvalEntry(border_color='#0069A9')
        self.factor_entry.setPlaceholderText(_("Real number or formula"))
        self.factor_entry.setToolTip(
            _("Enter the etch factor, for example 2.5 . Must be greater than 0.")
        )

        grid1.addWidget(self.factor_label, 10, 0)
        grid1.addWidget(self.factor_entry, 10, 1)

        # Manual Offset
        self.offset_label = FCLabel('%s:' % _('Offset'))
        self.offset_label.setToolTip(
            _("The exact amount to grow (or shrink) every copper feature, in microns [um].\n"
              "Use this when you already know the compensation you want, for example from\n"
              "measuring previous boards.\n"
              "A positive value grows the copper (the usual case); a negative value shrinks it.\n"
              "As a rough guide, the growth needed is about Copper Thickness / Etch Factor,\n"
              "for example 35 um / 2.5 is about 14 um.")
        )
        self.offset_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.offset_entry.set_precision(self.decimals)
        self.offset_entry.set_range(-10000.0000, 10000.0000)

        grid1.addWidget(self.offset_label, 12, 0)
        grid1.addWidget(self.offset_entry, 12, 1)

        # Hide the Etchants and Etch factor
        self.etchants_label.hide()
        self.etchants_combo.hide()
        self.factor_label.hide()
        self.factor_entry.hide()
        self.offset_label.hide()
        self.offset_entry.hide()

        # #############################################################################################################
        # Generate Etch Compensation Button
        # #############################################################################################################
        self.compensate_btn = FCButton(_('Compensate'), bold=True)
        self.compensate_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/etch_32.png'))
        self.compensate_btn.setToolTip(
            _("Grow the copper features to make up for the sideways etch, then create a new\n"
              "Gerber object named '<source>_comp'. The original object is not changed.\n"
              "Set the Source Object, Copper Thickness, and a Ratio method before clicking.")
        )
        self.tools_box.addWidget(self.compensate_btn)

        self.tools_box.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Clear all the fields above and return this tool to its default settings.\n"
              "Your loaded objects are not affected.")
        )
        self.layout.addWidget(self.reset_button)

        # #################################### FINSIHED GUI ###########################
        # #############################################################################

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

# end of file
