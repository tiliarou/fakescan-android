from pythonforandroid.recipe import PythonRecipe

class PyMuPDFRecipe(PythonRecipe):
    version = "1.24.0"
    url = "https://files.pythonhosted.org/packages/source/P/PyMuPDF/PyMuPDF-{version}.tar.gz"
    name = "pymupdf"
    depends = ["python3"]
    call_hostpython_via_targetpython = False
    install_in_hostpython = False

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env["PYMUPDF_SETUP_MUPDF_BUILD"] = "0"
        return env

recipe = PyMuPDFRecipe()
