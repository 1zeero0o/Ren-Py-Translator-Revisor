from pathlib import Path

from .catalog import parse_template, read_yaml
from .domain import Project, user_data_dir


def demo_project():
    root = user_data_dir() / "demo"
    (root / "game").mkdir(parents=True, exist_ok=True)
    script = '''# game/script.rpy:12
translate revisor_template start_18a340c2:

    # e "Welcome back, [player_name]."
    e "Welcome back, [player_name]."

# game/script.rpy:15
translate revisor_template start_04b628d9:

    # "The station was quieter than I remembered."
    "The station was quieter than I remembered."

# game/script.rpy:18
translate revisor_template start_2d5f902e:

    # e happy "There is still {i}one{/i} story left to tell."
    e happy "There is still {i}one{/i} story left to tell."

translate revisor_template strings:

    # game/script.rpy:21
    old "Stay a little longer"
    new "Stay a little longer"

    # game/screens.rpy:85
    old "Preferences"
    new "Preferences"

    # game/screens.rpy:88
    old "Return"
    new "Return"
'''
    entries = parse_template("script.rpy", script, "revisor_template")
    entries[0].update("Bem-vindo de volta, [player_name].", reviewed=True)
    entries[1].update("A estação estava mais silenciosa do que eu lembrava.", machine=True)
    entries[4].update("Preferências", reviewed=True)
    yaml_path = root / "dialogue.yml"
    yaml_path.write_text('chapter:\n  title: "A new beginning"\n  note: "Meet me at sunset."\n', "utf-8")
    docs, yaml_entries, _ = read_yaml({"data/dialogue.yml": yaml_path})
    return Project(str(root), "pt_BR", entries=entries + yaml_entries, templates={"script.rpy": script}, yaml_documents=docs,
                   workspace=str(root), warnings=["Projeto de demonstração: os identificadores de diálogo são ilustrativos."])
