import os
import unittest
import carb
import omni.kit.test
import omni.kit.ui_test
import omni.ui
from os.path import basename

class TestUsdPaths(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        # Disable logging for the time of tests to avoid spewing errors
        await omni.usd.get_context().new_stage_async()
        omni.kit.window.usd_paths.tests.create_test_stage()
        self.__window_name = omni.kit.window.usd_paths.UsdPathsExtension.WINDOW_NAME
        omni.ui.Workspace.show_window(self.__window_name, True)

    async def test_paths(self):
        # 1. reload paths, check if the values in text fields are correct
        window_ref = omni.kit.ui_test.find(self.__window_name)
        reload_button = window_ref.find("**/Button[*].text==' Reload paths '")
        self.assertTrue(reload_button)
        await reload_button.click()
        await self.wait_n_updates(1)
        path_refs = window_ref.find_all("**/ScrollingFrame[0]/**/StringField[*]")
        self.assertTrue(path_refs)
        file_names = sorted([basename(pr.widget.model.get_value_as_string()).lower()
                      for pr in path_refs])
        target_list = ["lenna.dds", "lenna.gif", "lenna.jpg", "lenna.png", "lenna.tga", "omnipbr.mdl", "sunflowers.hdr"]
        self.assertListEqual(file_names, target_list)

        # 2. search, replace, preview, then check if the values in text fields have been changed
        search_widget_ref = window_ref.find("**/StringField[*].identifier=='search_string_field'")
        replace_widget_ref = window_ref.find("**/StringField[*].identifier=='replace_string_field'")
        self.assertTrue(search_widget_ref)
        self.assertTrue(replace_widget_ref)
        await search_widget_ref.input("lenna")
        await replace_widget_ref.input("jenna")
        preview_button_ref = window_ref.find("**/Button[*].text==' Preview '")
        await preview_button_ref.click()

        path_refs = window_ref.find_all("**/ScrollingFrame[0]/**/StringField[*]")
        file_names = sorted([basename(pr.widget.model.get_value_as_string()).lower()
                      for pr in path_refs])
        target_list = ["jenna.dds", "jenna.gif", "jenna.jpg", "jenna.png", "jenna.tga", "omnipbr.mdl", "sunflowers.hdr"]
        self.assertListEqual(file_names, target_list)

        # 3. apply, check if the paths of textures have been changed
        apply_widget_ref = window_ref.find("**/Button[*].text==' Apply '")
        self.assertTrue(apply_widget_ref)
        await apply_widget_ref.click()

        stage = omni.usd.get_context().get_stage()
        diffuse_texture = stage.GetAttributeAtPath("/World/Looks/GroundMat/Shader.inputs:diffuse_texture")
        normalmap_texture = stage.GetAttributeAtPath("/World/Looks/GroundMat/Shader.inputs:normalmap_texture")
        reflectionroughness_texture = stage.GetAttributeAtPath("/World/Looks/GroundMat/Shader.inputs:reflectionroughness_texture")
        metallic_texture = stage.GetAttributeAtPath("/World/Looks/GroundMat/Shader.inputs:metallic_texture")
        ao_texture = stage.GetAttributeAtPath("/World/Looks/GroundMat/Shader.inputs:ao_texture")

        def check_name(texture, target_name):
            texture_name = basename(str(texture.Get())[1:-1])
            return texture_name == target_name

        self.assertTrue(check_name(diffuse_texture, 'jenna.dds'))
        self.assertTrue(check_name(normalmap_texture, 'jenna.jpg'))
        self.assertTrue(check_name(reflectionroughness_texture, 'jenna.png'))
        self.assertTrue(check_name(metallic_texture, 'jenna.tga'))
        self.assertTrue(check_name(ao_texture, 'jenna.gif'))
