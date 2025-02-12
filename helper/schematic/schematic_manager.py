import logging
import re
from pathlib import Path


logger = logging.getLogger("KICONV")


SYMBOL_RE = re.compile(r'^\s*\(symbol \"(?P<SYMBOL_NAME>.+)\" \(pin')


TEMPLATE_LIB_HEADER = b"""\
(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
"""
TEMPLATE_LIB_FOOTER = b")\n"


class SchematicExist(Exception):
    pass


class SchematicNotFound(Exception):
    pass


class SchematicManager:

    def __init__(self, path, name="lcsc"):
        self.lib_name = name
        self.lib_root = Path(path)
        self.path = self.lib_root.joinpath(f"{name}.kicad_sym")
        self.db = []
        self.alias = {}
        self._db_builded = False

        self.post_init_check()

    def post_init_check(self):
        if not self.lib_root.exists():
            logger.warning("Schematic Manager: Schematic Path not exists, create it.")
            self.lib_root.mkdir()

    def check_db(self):
        if not self._db_builded:
            self.build_schematic_db()

    def build_schematic_db(self, rebuild=False):
        if self._db_builded and not rebuild:
            logger.info(
                "Schematic Manager: [DB_BUILD] Schematic DB already build, skip."
            )
            return

        self._db_builded = True
        last_def = None

        if not self.path.exists():
            return

        with self.path.open('r',encoding='utf-8') as fp:
            for line in fp:
                # line = line.strip()
                # if line == "" or line[0] == "#":
                #     continue
                m = SYMBOL_RE.match(line)

                if m:
                    self.db.append(m.group('SYMBOL_NAME'))

                # # find def name
                # if line[:3] == 'DEF':
                #     last_def = line.split(' ')[1]
                #     self.db.append(last_def)

                # elif line[:5] == 'ALIAS':
                #     als = line.split(' ')[1:]
                #     for ali in als:
                #         self.alias[ali] = last_def

    def get_schematic(self, schematic_title):
        self.check_db()

        if schematic_title in self.db:
            return True

        # if schematic_title in self.alias:
        #     return self.alias[schematic_title]

        return False

    def update_schematic(self, schematic_title, schematic_data):
        sch_find = False
        start_pos = 0
        # sch_magic = f"  (symbol \"{schematic_title}\" (pin_names".encode()

        with self.path.open('rb+') as fp:
            while True:
                line = fp.readline()
                m = SYMBOL_RE.match(line.decode())
                if m and m.group('SYMBOL_NAME') == schematic_title:
                    sch_find = True
                    logger.debug(
                        "Schematic Manager: Find Sch at C-pos %s. Line Size: %s",
                        fp.tell(),
                        len(line)
                    )

                    fp.seek(-len(line), 1)
                    start_pos = fp.tell()
                    logger.debug(
                        f"Schematic Manager: Sch S-pos at %s.",
                        start_pos
                    )
                    fp.readline()
                    break

            # buffer remind ctx
            if not sch_find:
                logger.critical("Schematic Manager: Unable to update schematic, schematic not find.")
                raise SchematicNotFound()

            buffer = None

            while True:
                line = fp.readline()
                m = SYMBOL_RE.match(line.decode())
                if m:
                    print(line)
                    buffer = line + fp.read()
                    break

            fp.seek(start_pos, 0)
            fp.truncate()
            fp.write(schematic_data.encode())
            fp.write(b'\n')
            fp.write(buffer)

    def add_schematic(
        self,
        schematic_title,
        schematic_data,
        update=False,
        auto_alias_rename=True
    ):
        logger.info("Schematic Manager: Add Schematic %s.", schematic_title)
        db_sch = self.get_schematic(schematic_title)

        if db_sch:
            if isinstance(db_sch, bool):
                if not update:
                    logger.warning(
                        "Schematic Manager: [ADD_SCH] %s already in DB.",
                        schematic_title
                    )
                    raise SchematicExist()
                return self.update_schematic(schematic_title, schematic_data)
            # else:
            #     logger.warning(
            #         "Schematic Manager: [ADD_SCH] %s has alias with %s.",
            #         schematic_title,
            #         db_sch
            #     )

            #     new_schematic_title = schematic_title + "-LC"
            #     logger.warning(
            #         "Schematic Manager: [ADD_SCH] Auto Rename Schematic to %s.",
            #         new_schematic_title
            #     )
            #     schematic_data = schematic_data.replace(
            #         f'DEF "{schematic_title}"',
            #         f'DEF "{new_schematic_title}"'
            #     )
            #     schematic_data = schematic_data.replace(
            #         f'# {schematic_title}',
            #         f'# {new_schematic_title}'
            #     )
            #     schematic_title = new_schematic_title

        # create file if not exist
        if not self.path.exists():
            ctx = TEMPLATE_LIB_HEADER + schematic_data.encode() + b"\n"
            ctx += TEMPLATE_LIB_FOOTER
            self.path.write_bytes(ctx)
        else:
            with self.path.open('rb+') as fp:
                fp.seek(-len(TEMPLATE_LIB_FOOTER), 2)
                fp.truncate()
                fp.write(schematic_data.encode())
                fp.write(b'\n')
                fp.write(TEMPLATE_LIB_FOOTER)

        self.db.append(schematic_title)
        logger.info("Schematic Manager: Schematic %s Added.", schematic_title)
