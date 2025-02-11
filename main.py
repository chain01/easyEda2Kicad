import wx
import wx.svg
import wx.lib.agw.hyperlink as hl

import requests
import webbrowser
# import threading
import io
import re
import time
import logging

from datetime import datetime

from logging import Handler, Formatter
from cairosvg.parser import Tree as svgTree
from cairosvg.surface import SVGSurface, PNGSurface

from gui_lib_manager import LibManagerControl
from gui_adv_search import AdvSearchControl


logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s [%(levelname)s]<%(funcName)s:%(lineno)d> %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

LCID_RE = re.compile(r"C\d+", re.I)


PDF_ICON = "assets/pdf.svg"
LC_ICON = "assets/lc.png"


PART_INFO_CONF = {
    'brand': {
        'label': '品牌',
        'name': 'brand',
        'lc_key': 'Manufacturer',
    },
    'model': {
        'label': '厂家编号',
        'name': 'model',
        'lc_key': 'Manufacturer Part'
    },
    'package': {
        'label': '封装',
        'name': 'package',
        'lc_key': 'Supplier Footprin'
    },
    'catelog': {
        'label': '分类',
        'name': 'catelog',
        'lc_key': 'parentCatalogName'
    },
    'sub_catelog': {
        'label': '子类',
        'name': 'sub_catelog',
        'lc_key': 'catalogName'
    },
    'desc': {
        'label': '描述',
        'name': 'desc',
        'lc_key': 'description',
        'multiline': True
    }
}


class WxHandler(Handler):
    def __init__(self, func):
        Handler.__init__(self)
        self.status_write_func = func
        self.formatter = Formatter(
            fmt='%(asctime)s [%(levelname)s] %(message)s\n',
            datefmt='%H:%M:%S'
        )

    def emit(self, record):
        msg = self.format(record)
        self.status_write_func(msg)


def load_asset(path):
    with open(path, 'rb') as fp:
        return io.BytesIO(fp.read())


def svg_conv(svg):
    tree = svgTree(bytestring=svg, unsafe=False)
    output = io.BytesIO()
    instance = SVGSurface(tree, output, 96, scale=1)
    instance.finish()

    return output.getvalue()


def svgpng_conv(svg, scale=10):
    if isinstance(svg, io.BytesIO):
        svg = svg.getvalue()
    tree = svgTree(bytestring=svg, unsafe=False)
    output = io.BytesIO()
    instance = PNGSurface(tree, output, 96, scale=scale)
    instance.finish()

    output.seek(0)
    return output


def img_resize(img, size_h, size_w):
    h = img.GetWidth()
    w = img.GetHeight()
    if w > h:
        new_w = int(size_w)
        new_h = int(size_h * h / w)
    else:
        new_h = int(size_h)
        new_w = int(size_w * w / h)

    img = img.Scale(new_h, new_w, wx.IMAGE_QUALITY_HIGH)

    return img


def DrawFilledBitmap(width, height, color=None, label=None):
    if color is None:
        color = wx.Colour("#FFFFFFD0")
    canvas = wx.Bitmap(width, height)

    mdc = wx.MemoryDC()
    mdc.SelectObject(canvas)

    mdc.SetBackground(wx.Brush(color))
    mdc.Clear()

    if label is not None:
        # mdc.SetPen(wx.Pen(wx.Colour("#000000")))
        x = int(width / 5)
        y = int(height / 2 - 10)
        r = wx.Rect(x, y, x * 3, 20)
        # mdc.DrawRectangle(r)
        # mdc.SetTextForeground(wx.Colour("#000000"))
        mdc.DrawLabel(label, r, wx.ALIGN_CENTER)

    mdc.SelectObject(wx.NullBitmap)

    return canvas


def warn_dialog(msg):
    wx.MessageBox(msg, 'Error', wx.OK | wx.ICON_ERROR)


class SVGMixin:
    def load_svg(self, data, bbox):
        self.svg = data
        self.bbox = bbox

    def get_bitmap(self, scale=1):
        bscale = min(600 / self.bbox['width'], 600 / self.bbox['height'])
        png_scale = 1 if bscale < 0 else bscale

        png = svgpng_conv(self.svg.encode(), png_scale)
        # png.seek(0)

        # wx_png = wx.Bitmap(wx.Image(png))
        img = wx.Image(png)
        h = img.GetWidth()
        w = img.GetHeight()
        i_size = 240
        if w > h:
            new_w = int(i_size)
            new_h = int(i_size * h / w)
        else:
            new_h = int(i_size)
            new_w = int(i_size * w / h)

        img = img.Scale(new_h, new_w, wx.IMAGE_QUALITY_HIGH)
        wx_png = wx.Bitmap(img)

        return wx_png


class EDAData:
    TYPE = -1

    def __init__(self, component_uuid, update_time=None):
        self.uuid = component_uuid
        self.update_time = update_time


class EDASymbol(EDAData, SVGMixin):
    TYPE = 2


class EDAFootprint(EDAData, SVGMixin):
    TYPE = 4


class LCPART:

    def __init__(self, lcid):
        self.lcid = lcid.upper()
        self.svg_loaded = False
        self.footprint = None
        self.symbol = None

        self.part_detail = {}
        self.part_loaded = False

    def get_lcsc_link(self):
        return f"https://lcsc.com/product-detail/{self.lcid}.html"

    def get_ds_link(self):
        if not self.part_loaded:
            self.get_part_detail_from_easyeda()
        return self.part_detail["attributes"].get('Datasheet', "")

    def get_part_info(self):
        if not self.part_loaded:
            self.get_part_detail_from_easyeda()
        return self.part_detail

    def get_part_name(self):
        if not self.part_loaded:
            self.get_part_detail_from_easyeda()

        print(self.part_detail.get("title", "N / A"))
        return self.part_detail.get("title", "N / A")

    def get_part_img(self):
        if not self.part_loaded:
            self.get_part_detail_from_easyeda()
        img_urls = self.part_detail.get("images", None)  # type: ignore

        if img_urls is None or len(img_urls) == 0:
            return None

        url = img_urls[0]

        req = requests.get(url)
        if req.status_code != 200:
            return None

        img = wx.Image(io.BytesIO(req.content))
        img = img_resize(img, 200, 200)

        return img

    def get_part_detail_from_easyeda(self):
        logger.info("获取器件信息")#翻译：获取部件信息
        # req = requests.get(f'https://wwwapi.lcsc.com/v1/products/detail?product_code={self.lcid}')
        # req = requests.get(f'https://wmsc.lcsc.com/wmsc/product/detail?productCode={self.lcid}')
        payload = {
            'pageSize': 50,
            'page': 1,
            'returnListStyle': 'classifyarr',
            'wd': self.lcid
        }
        r = requests.post(
            "https://pro.lceda.cn/api/devices/search",
            data=payload
        )
        data = r.json()

        if isinstance(data, dict):
            self.part_detail = data['result']['lists']['lcsc'][0]

        self.part_loaded = True

    def get_svg_from_easyeda(self):
        self.svg_loaded = True
        logger.info("获取符号和封装")#翻译：获取部件符号和封装
        req = requests.get(
            f'https://easyeda.com/api/products/{self.lcid}/svgs'
        )

        data = req.json()

        if data['code'] != 0:
            # warn_dialog(
            #     f"Cannot get SVG from EasyEDA.\nCode: {data['message']}"
            # )
            msg = [
                "Unable to get SVG from EasyEDA.",
                f"Code: {data['message']}"
            ]
            logger.warning(" ".join(msg))
            return

        for component in data['result']:
            if component['docType'] == 2:
                self.symbol = EDASymbol(component['component_uuid'],
                                        component['updateTime'])
                self.symbol.load_svg(component['svg'], component['bbox'])
            elif component['docType'] == 4:
                self.footprint = EDASymbol(component['component_uuid'],
                                           component['updateTime'])
                self.footprint.load_svg(component['svg'], component['bbox'])
            else:
                logger.warning(
                    f"unknow doc type: {component['docType']}, {component}"
                )

    def get_footprint_img(self, **kwargs):
        if not self.svg_loaded:
            self.get_svg_from_easyeda()

        if self.footprint is None:
            return DrawFilledBitmap(250, 250, label="NOT AVALIABLE")

        return self.footprint.get_bitmap(**kwargs)

    def get_symbol_img(self, **kwargs):
        if not self.svg_loaded:
            self.get_svg_from_easyeda()

        if self.symbol is None:
            return DrawFilledBitmap(250, 250, label="NOT AVALIABLE")

        return self.symbol.get_bitmap(**kwargs)


class Main(wx.Frame):
    def __init__(self, *args, **kwds):
        kwds["style"] = kwds.get("style", 0) | wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)
        self.SetSize((900, 770))
        self.SetTitle("立创KiCAD封装转换工具")

        self.panel_1 = wx.Panel(self, wx.ID_ANY)

        sizer_1 = wx.BoxSizer(wx.VERTICAL)

        sizer_2 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_1.Add(sizer_2, 0, 0, wx.BOTTOM)

        label_1 = wx.StaticText(
            self.panel_1, wx.ID_ANY, "料号:", style=wx.ALIGN_RIGHT
        )
        label_1.SetMinSize((50, 22))
        sizer_2.Add(label_1, 0, 0, 0)

        self.ctl_lcid = wx.TextCtrl(self.panel_1, wx.ID_ANY, "")
        self.ctl_lcid.SetMinSize((250, 22))
        sizer_2.Add(self.ctl_lcid, 0, 0, 0)

        self.btn_search = wx.Button(self.panel_1, wx.ID_ANY, "搜索")
        self.btn_search.SetMinSize((84, 22))
        self.btn_search.Bind(wx.EVT_BUTTON, self.on_btn_search_pressed)
        sizer_2.Add(self.btn_search, 0, 0, 0)

        sizer_2.Add((20, 20), 0, 0, 0)

        self.btn_save_to_kicad = wx.Button(self.panel_1, wx.ID_ANY, "保存")
        self.btn_save_to_kicad.SetMinSize((84, 22))
        self.btn_save_to_kicad.Bind(
            wx.EVT_BUTTON, self.on_btn_save_kicad_pressed)
        sizer_2.Add(self.btn_save_to_kicad, 0, 0, 0)

        sizer_2.Add((20, 20), 0, 0, 0)

        self.btn_adv_search = wx.Button(self.panel_1, wx.ID_ANY, "高级搜索")
        self.btn_adv_search.SetMinSize((84, 22))
        self.btn_adv_search.Bind(wx.EVT_BUTTON, self.btn_adv_search_pressed)
        sizer_2.Add(self.btn_adv_search, 0, 0, 0)

        # part root
        product_root_sizer = wx.BoxSizer(wx.HORIZONTAL)
        product_root_sizer.AddSpacer(5)
        sizer_1.AddSpacer(5)
        sizer_1.Add(product_root_sizer, 1, wx.EXPAND, 0)

        # part info (left panel)
        part_info_sizer = wx.BoxSizer(wx.VERTICAL)
        product_root_sizer.Add(part_info_sizer, 1, wx.EXPAND, 0)

        part_titlebar_sizer = wx.BoxSizer(wx.HORIZONTAL)
        page_name_sizer = wx.BoxSizer(wx.HORIZONTAL)
        part_titlebar_sizer.Add(page_name_sizer, 1, wx.EXPAND, 0)
        part_titlebar_sizer.AddSpacer(10)

        self.part_name = wx.StaticText(self.panel_1, wx.ID_ANY, "")
        self.part_name.SetFont(
            wx.Font(
                15,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
                0,
                ""
            )
        )
        page_name_sizer.Add(self.part_name, 0, 0, 0)
        part_info_sizer.Add(part_titlebar_sizer, 0, wx.EXPAND, 0)
        part_info_sizer.AddSpacer(5)

        sizer_4 = wx.BoxSizer(wx.HORIZONTAL)
        part_info_sizer.Add(sizer_4, 1, wx.EXPAND, 0)

        sizer_5 = wx.BoxSizer(wx.VERTICAL)
        sizer_4.Add(sizer_5, 0, wx.EXPAND, 0)

        self.prodcut_picture = wx.StaticBitmap(
            self.panel_1,
            wx.ID_ANY,
            DrawFilledBitmap(200, 200, label="元件图片\n未找到")
        )
        self.prodcut_picture.SetMinSize((200, 200))
        sizer_5.Add(self.prodcut_picture, 0, 0, 0)

        self.panel_3 = wx.ScrolledWindow(
            self.panel_1, wx.ID_ANY, style=wx.TAB_TRAVERSAL
        )
        self.panel_3.SetScrollRate(10, 10)
        sizer_4.AddSpacer(20)
        sizer_4.Add(self.panel_3, 1, wx.EXPAND, 0)

        # Part Details
        sizer_6 = wx.BoxSizer(wx.VERTICAL)

        part_info_row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer_6.Add(part_info_row_sizer, 0, wx.EXPAND, 0)

        t_part_info = wx.StaticText(self.panel_3, wx.ID_ANY, "手册")
        t_part_info.SetFont(
            wx.Font(
                14,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
                0,
                ""
            )
        )
        # t_part_info.SetMinSize((-1, 20))
        part_info_row_sizer.Add(t_part_info, 1, wx.EXPAND, 0)

        ds_ref_sizer = wx.BoxSizer(wx.HORIZONTAL)
        part_info_row_sizer.Add(ds_ref_sizer, 0, 0, 0)

        ds_img = svgpng_conv(load_asset(PDF_ICON), 1)
        ds_img = img_resize(wx.Image(ds_img), 25, 25)
        self.btn_ds = wx.BitmapButton(
            self.panel_3,
            wx.ID_ANY,
            wx.Bitmap(ds_img),
            size=(16, 16),
            style=wx.BORDER_NONE
        )
        self.btn_ds.Bind(wx.EVT_BUTTON, self.on_btn_ds_pressed)
        self.btn_ds.Disable()
        ds_ref_sizer.Add(self.btn_ds, 0, 0, 0)
        ds_ref_sizer.AddSpacer(10)

        ref_img = img_resize(wx.Image(load_asset(LC_ICON)), 16, 16)
        self.btn_ref = wx.BitmapButton(
            self.panel_3,
            wx.ID_ANY,
            wx.Bitmap(ref_img),
            pos=(0, 0),
            size=(16, 16),
            style=wx.BORDER_NONE
        )
        self.btn_ref.Bind(wx.EVT_BUTTON, self.on_btn_ref_pressed)
        self.btn_ref.Disable()
        ds_ref_sizer.Add(self.btn_ref, 0, 0, 0)
        ds_ref_sizer.AddSpacer(64)
        self.part_info_row_sizer = part_info_row_sizer
        self.ds_ref_sizer = ds_ref_sizer
        # part_info_row_sizer.Hide(ds_ref_sizer)

        sizer_6.AddSpacer(10)

        self.part_attrs = {}
        for attr_conf in PART_INFO_CONF.values():
            t = self.make_part_attr_pairs(panel=self.panel_3, **attr_conf)
            sizer_6.Add(t, 0, 0, 0)
            sizer_6.AddSpacer(10)

        sizer_3 = wx.BoxSizer(wx.VERTICAL)
        product_root_sizer.Add(sizer_3, 0, 0, 0)
        product_root_sizer.AddSpacer(5)

        self.img_EDASymbol = wx.StaticBitmap(
            self.panel_1, wx.ID_ANY, DrawFilledBitmap(250, 250))
        self.img_EDASymbol.SetMinSize((250, 250))
        sizer_3.Add(self.img_EDASymbol, 0, 0, 0)

        sizer_3.AddSpacer(5)

        self.img_EDAFootprint = wx.StaticBitmap(
            self.panel_1, wx.ID_ANY, DrawFilledBitmap(250, 250))
        self.img_EDAFootprint.SetMinSize((250, 250))
        sizer_3.Add(self.img_EDAFootprint, 0, 0, 0)

        self.panel_2 = wx.Panel(self.panel_1, wx.ID_ANY)
        self.panel_2.SetMinSize((900, 200))
        sizer_1.Add(self.panel_2, 0, wx.EXPAND, 0)

        panel_2_sizer = wx.BoxSizer(wx.VERTICAL)

        log_name = wx.StaticText(self.panel_2, wx.ID_ANY, "Logs")
        log_name.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT,
                         wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, 0, ""))
        panel_2_sizer.Add(log_name, 0, 0, 0)

        self.status = wx.TextCtrl(
            self.panel_2,
            style=wx.TE_MULTILINE | wx.TE_READONLY
        )
        panel_2_sizer.Add(self.status, 1, wx.ALL | wx.EXPAND, 5)

        self.panel_2.SetSizer(panel_2_sizer)

        self.panel_3.SetSizer(sizer_6)

        self.panel_1.SetSizer(sizer_1)

        self.part_eda_id = wx.NewIdRef()
        self.part_lceda_id = wx.NewIdRef()

        # menubar = wx.MenuBar()
        # addMenu = wx.Menu()
        # easyeda_part = addMenu.Append(self.part_eda_id, 'EasyEda Part', 'EasyEda Part')
        # # easyeda_part.Bind(wx.EVT_MENU, lambda x: self.add_part_by_uuid(True))
        # lceda_part = addMenu.Append(self.part_lceda_id, 'LcEDA Part', 'LcEDA Part')
        # # lceda_part.Bind(wx.EVT_MENU, lambda x: self.add_part_by_uuid(False))

        # addMenu.Bind(wx.EVT_MENU, self.add_part_by_uuid)
        # menubar.Append(addMenu, 'Add Part')

        # self.SetMenuBar(menubar)

        self.Layout()
        self.init_values()

    def status_write(self, msg):
        # ts = datetime.now().strftime('%H:%M:%S')
        self.status.WriteText(msg)
        # self.status.Update()

    def log_init(self):
        wx_log = WxHandler(self.status_write)
        wx_log.setLevel(logging.INFO)
        logger.addHandler(wx_log)

    def init_values(self):
        self.lcpart = None
        self.lib_manager = None
        self.advsearch_manager = None

        self.log_init()
        self.status.WriteText("Init Done.\nVersion: Alpha.\n")
        logger.debug('DEBUG MODE: ON')

    def add_part_by_uuid(self, e):
        # print(e.GetId(), self.part_eda_id)
        source = "EasyEda"
        source_easyeda = True
        if e.GetId() == self.part_lceda_id.GetId():
            source = 'LcEda'
            source_easyeda = False

        dlg = wx.TextEntryDialog(
            self, f'Please entry {source} part UUID.'
        )
        ret = dlg.ShowModal()
        if ret != wx.ID_OK:
            return

        value = dlg.GetValue().strip()
        dlg.Destroy()

        if value == "":
            warn_dialog('Part UUID Cannot be empty.')
            return

        if self.lib_manager is None:
            self.lib_manager = LibManagerControl(self)

        self.lib_manager.load_part(
            value,
            direct_part=True,
            source_easyeda=source_easyeda
        )

    def make_part_attr_pairs(self, panel, name, label, **kwargs):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(5)

        attr_name = wx.StaticText(
            panel, wx.ID_ANY, label
        )
        attr_name.SetFont(
            wx.Font(
                11,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
                0,
                ""
            )
        )
        attr_name.SetMinSize((100, 20))
        sizer.Add(attr_name, 0, 0, 0)
        sizer.AddSpacer(10)

        multiline = kwargs.get('multiline', False)

        attr_value_style = wx.TE_READONLY | wx.BORDER_NONE
        if multiline:
            attr_value_style = wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE

        attr_value = wx.TextCtrl(
            panel,
            wx.ID_ANY,
            "",
            style=attr_value_style,
        )
        attr_value.SetFont(
            wx.Font(
                11,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                0,
                ""
            )
        )
        height = 60 if multiline else 20
        attr_value.SetMinSize((250, height))
        sizer.Add(attr_value, 1, wx.EXPAND, 5)

        self.part_attrs[name] = attr_value

        return sizer

    def on_btn_ds_pressed(self, e):
        if self.lcpart is None:
            wx.MessageBox("No LC Part", 'Info', wx.OK | wx.ICON_INFORMATION)
            return

        url = self.lcpart.get_ds_link()
        if url == "":
            wx.MessageBox("No Datasheet Avaliable.", 'Info',
                          wx.OK | wx.ICON_INFORMATION)
            return
        webbrowser.open(url)

    def on_btn_ref_pressed(self, e):
        if self.lcpart is None:
            wx.MessageBox("No LC Part", 'Info', wx.OK | wx.ICON_INFORMATION)
            return

        url = self.lcpart.get_lcsc_link()
        webbrowser.open(url)

    def on_btn_search_pressed(self, e):
        lcid = self.ctl_lcid.GetValue()

        if not lcid:
            warn_dialog("料号不能为空.")
            return

        if not LCID_RE.match(lcid):
            warn_dialog(f"<{lcid}> 不是有效的立创料号.")
            return

        logger.info(f"获取信息: {lcid}")

        self.lcpart = LCPART(lcid)
        print(self.lcpart)
        self.img_EDASymbol.SetBitmap(
            self.lcpart.get_symbol_img()
        )
        self.img_EDAFootprint.SetBitmap(
            self.lcpart.get_footprint_img()
        )

        # product Info
        product_img = self.lcpart.get_part_img()
        if product_img:
            self.prodcut_picture.SetBitmap(
                wx.Bitmap(product_img)
            )

        # product name
        self.part_name.SetLabelText(self.lcpart.get_part_name())

        # update part info
        part_info = self.lcpart.get_part_info()
        # for attr in PART_INFO_CONF.values():
        #     lc_value = part_info.get(attr['lc_key'], '-')  self.part_attrs[PART_INFO_CONF['name']].SetValue(str(lc_value))
        print("厂商:", part_info["attributes"].get('Manufacturer', '-'))
        self.part_attrs[PART_INFO_CONF['brand']['name']].SetValue(
            str(part_info["attributes"].get('Manufacturer', '-'))
        )
        print("厂家编号:", part_info["attributes"].get('Manufacturer Part', '-'))
        self.part_attrs[PART_INFO_CONF['model']['name']].SetValue(
            str(part_info["attributes"].get('Manufacturer Part', '-'))
        )
        print("封装:", part_info["attributes"].get('Supplier Footprint', '-'))
        self.part_attrs[PART_INFO_CONF['package']['name']].SetValue(
            str(part_info["attributes"].get('Supplier Footprint', '-'))
        )
        print("分类:", part_info["tags"]["parent_tag"].get('name_cn', '-'))
        self.part_attrs[PART_INFO_CONF['catelog']['name']].SetValue(
            str(part_info["tags"]["parent_tag"].get('name_cn', '-'))
        )
        print("子类:", part_info["tags"]["child_tag"].get('name_cn', '-'))
        self.part_attrs[PART_INFO_CONF['sub_catelog']['name']].SetValue(
            str(part_info["tags"]["child_tag"].get('name_cn', '-'))
        )
        print("描述:", part_info.get('description', '-'))
        self.part_attrs[PART_INFO_CONF['desc']['name']].SetValue(
            str(part_info.get('description', '-'))
        )
        # show datasheet & web ref btn
        self.btn_ds.Enable()
        self.btn_ref.Enable()

        logger.info(f"获取完成")

    def btn_adv_search_pressed(self, e):
        if self.advsearch_manager is None:
            self.advsearch_manager = AdvSearchControl(self)

        ret = self.advsearch_manager.show()

        if ret == wx.OK and self.advsearch_manager.lcsc_part:
            self.ctl_lcid.SetValue(self.advsearch_manager.lcsc_part)
            logger.info(f"Search....")

            self.on_btn_search_pressed(None)

    def on_btn_save_kicad_pressed(self, e):
        if self.lcpart is None:
            warn_dialog("No LC Part to save.")
            return

        if self.lib_manager is None:
            self.lib_manager = LibManagerControl(self)

        self.lib_manager.load_part(
            self.lcpart.lcid, self.lcpart.part_detail)    # type: ignore
        # self.lib_manager.load_part("C9872")


class MyApp(wx.App):
    def OnInit(self):
        self.frame = Main(None, wx.ID_ANY, "")
        self.SetTopWindow(self.frame)
        self.frame.Show()
        return True


if __name__ == "__main__":
    app = MyApp(0)
    app.MainLoop()
