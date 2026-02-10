"""
Dynamic Shop Product Placer for IsaacSim

Flags:
    use_current_scene = True (default)
        - True:  adds Shelf into currently open GUI scene
        - False: opens the empty shop as a new stage (original behavior)

    APPLY_SHELF_WORLD_XFORM (default False)
        - If True: apply a world transform (translate/rotate) on /World/Shelf

    SHELF_WORLD_XFORM_MODE:
        - "additive": compose on top of referenced shelf transform
        - "override": reset xform stack so referenced shelf pose is ignored
"""

import omni.usd
from pxr import Usd, UsdGeom, Gf, UsdPhysics, PhysxSchema, Sdf
import random
import math
import json
from pathlib import Path

BASE_PATH = "/workspace/isaac_sim_dynamic_store/"

# ==============================
# USER FLAGS
# ==============================
use_current_scene = True   # True = keep GUI scene, False = open new stage (original)

# Apply a world transform to the Shelf prim (/World/Shelf) after it is created/referenced
APPLY_SHELF_WORLD_XFORM = False

# World-space translation in meters
SHELF_WORLD_TRANSLATE = (0.0, 0.0, 0.0)

# World-space rotation in degrees, ZYX order (same convention as UsdGeom.Xform.AddRotateZYXOp)
SHELF_WORLD_ROTATE_ZYX_DEG = (0.0, 0.0, 0.0)

# "additive" (compose with referenced shelf pose) or "override" (ignore referenced shelf pose)
SHELF_WORLD_XFORM_MODE = "additive"  # "additive" or "override"
# ==============================

ENABLE_PHYSICS_FOR_ALL = True
FORCE_COLLISION_FOR_PHYSICS = True


def load_product_data():
    """Load product data from JSON file."""
    json_file_path = Path(BASE_PATH) / "assets" / "product_data.json"
    try:
        with open(json_file_path, "r") as f:
            product_data = json.load(f)
        print(f"Loaded product data from: {json_file_path}")
        return product_data
    except Exception as e:
        print(f"ERROR loading product data: {e}")
        return {}


PRODUCT_DATA = load_product_data()


class DynamicShopPlacer:
    def __init__(self):
        self.stage = omni.usd.get_context().get_stage()
        base_file = Path(BASE_PATH) / "assets" / "Shop Minimal Empty.usda"
        self.empty_shop_path = str(base_file)

    # ------------------------------------------------------------------
    # NEW: apply a world-space transform to /World/Shelf
    # ------------------------------------------------------------------
    def apply_shelf_world_transform_if_enabled(self):
        if not APPLY_SHELF_WORLD_XFORM:
            return True

        shelf_prim = self.stage.GetPrimAtPath("/World/Shelf")
        if not shelf_prim or not shelf_prim.IsValid():
            print("ERROR: Cannot apply world transform: /World/Shelf does not exist.")
            return False

        xform = UsdGeom.Xform(shelf_prim)

        # In override mode, we reset xform stack so the referenced shelf's authored transforms are ignored
        if SHELF_WORLD_XFORM_MODE.lower() == "override":
            # Reset means: only the ops authored here define the transform stack
            xform.SetResetXformStack(True)
        else:
            # Additive mode: keep referenced shelf transforms, and compose additional ops here
            xform.SetResetXformStack(False)

        # Clear ops on the referencing prim so reruns don't accumulate multiple translate/rotate ops
        xform.ClearXformOpOrder()

        t = Gf.Vec3d(*SHELF_WORLD_TRANSLATE)
        r = Gf.Vec3f(*SHELF_WORLD_ROTATE_ZYX_DEG)

        translate_op = xform.AddTranslateOp()
        translate_op.Set(t)

        rotate_op = xform.AddRotateZYXOp()
        rotate_op.Set(r)

        xform.SetXformOpOrder([translate_op, rotate_op])

        print(
            f"Applied Shelf world xform ({SHELF_WORLD_XFORM_MODE}): "
            f"T={SHELF_WORLD_TRANSLATE}, R_ZYX_deg={SHELF_WORLD_ROTATE_ZYX_DEG}"
        )
        return True

    # ------------------------------------------------------------------
    # NEW: add shelf INTO EXISTING SCENE (no stage change)
    # ------------------------------------------------------------------
    def add_shelf_to_existing_stage(self):
        """
        References /World/Shelf from the empty shop USD
        into the currently open GUI scene.
        """
        self.stage = omni.usd.get_context().get_stage()
        if not self.stage:
            print("ERROR: No stage open in the GUI.")
            return False

        target_shelf_path = "/World/Shelf"
        src_prim_path = "/World/Shelf"

        shelf_prim = self.stage.GetPrimAtPath(target_shelf_path)
        if not shelf_prim or not shelf_prim.IsValid():
            shelf_prim = UsdGeom.Xform.Define(self.stage, target_shelf_path).GetPrim()

        # Clear old references if rerunning
        shelf_prim.GetReferences().ClearReferences()

        # Reference the shelf ONLY (not the full scene)
        shelf_prim.GetReferences().AddReference(
            Sdf.Reference(assetPath=self.empty_shop_path, primPath=src_prim_path)
        )

        print(f"Referenced Shelf into current stage: {self.empty_shop_path}:{src_prim_path}")

        # Apply optional world xform AFTER the reference is authored
        return self.apply_shelf_world_transform_if_enabled()

    # ------------------------------------------------------------------
    # ORIGINAL BEHAVIOR (open new stage)
    # ------------------------------------------------------------------
    def load_empty_shop_sync(self):
        print("Loading empty shop environment (NEW STAGE)...")
        success = omni.usd.get_context().open_stage(str(self.empty_shop_path))
        if not success:
            print(f"Failed to load empty shop from: {self.empty_shop_path}")
            return False

        self.stage = omni.usd.get_context().get_stage()
        print(f"Successfully loaded empty shop: {self.empty_shop_path}")

        # Even in "new stage" mode, you might still want to force a shelf world xform
        return self.apply_shelf_world_transform_if_enabled()

    # ------------------------------------------------------------------
    def create_product_hierarchy(self):
        shelf_prim = self.stage.GetPrimAtPath("/World/Shelf")
        if not shelf_prim or not shelf_prim.IsValid():
            print("ERROR: /World/Shelf does NOT exist!")
            return False

        shelf_categories = {}
        for product_id, product_data in PRODUCT_DATA.items():
            shelf = product_data.get("shelf", "Items_Lower")
            category = product_data.get("category", "Unknown")
            shelf_categories.setdefault(shelf, set()).add(category)

        for shelf_level, categories in shelf_categories.items():
            shelf_path = f"/World/Shelf/{shelf_level}"
            UsdGeom.Scope.Define(self.stage, shelf_path)
            for category in categories:
                category_path = f"{shelf_path}/{category}"
                UsdGeom.Scope.Define(self.stage, category_path)

        print("Created product hierarchy.")
        return True

    # ------------------------------------------------------------------
    def place_product(self, product_id, product_data):
        shelf_level = product_data.get("shelf", "Items_Lower")
        category = product_data.get("category", "Unknown")

        product_path = f"/World/Shelf/{shelf_level}/{category}/{product_id}"
        product_prim = self.stage.DefinePrim(product_path)
        product_prim.GetPayloads().AddPayload(product_data["asset"])

        xform = UsdGeom.Xform(product_prim)
        xform.ClearXformOpOrder()

        translate_op = xform.AddTranslateOp()
        translate_op.Set(Gf.Vec3d(*product_data["translate"]))

        scale_op = xform.AddScaleOp()
        scale_op.Set(Gf.Vec3f(*product_data["scale"]))

        rotation_op = None
        if "rotate" in product_data:
            rotation_op = xform.AddRotateZYXOp()
            rotation_op.Set(Gf.Vec3f(*product_data["rotate"]))
        elif "orient" in product_data:
            rotation_op = xform.AddOrientOp()
            q = product_data["orient"]
            rotation_op.Set(Gf.Quatf(q[0], Gf.Vec3f(q[1], q[2], q[3])))

        if rotation_op:
            xform.SetXformOpOrder([translate_op, rotation_op, scale_op])
        else:
            xform.SetXformOpOrder([translate_op, scale_op])

        print(f"Placed product: {product_id} at {product_data['translate']}")
        return True

    # ------------------------------------------------------------------
    def randomize_product_rotations(self, product_data_dict, num_products=3):
        randomized_data = product_data_dict.copy()
        product_ids = list(randomized_data.keys())
        selected_products = random.sample(product_ids, min(num_products, len(product_ids)))

        for pid in selected_products:
            pd = randomized_data[pid].copy()
            random_rotation = [
                random.uniform(-180, 180),
                random.uniform(-180, 180),
                random.uniform(-180, 180),
            ]
            pd["rotate"] = random_rotation
            pd.pop("orient", None)
            randomized_data[pid] = pd
            print(f"Randomized rotation for {pid}: {random_rotation}")

        return randomized_data

    # ------------------------------------------------------------------
    def place_all_products(self):
        randomized_product_data = self.randomize_product_rotations(PRODUCT_DATA, 3)
        success_count = 0

        for pid, pdata in randomized_product_data.items():
            try:
                if self.place_product(pid, pdata):
                    success_count += 1
            except Exception as e:
                print(f"Error placing {pid}: {e}")

        print(f"Placed {success_count}/{len(randomized_product_data)} products")
        return success_count > 0

    # ------------------------------------------------------------------
    def setup_scene_sync(self):
        print("Starting dynamic shop setup...")

        if use_current_scene:
            print("USING CURRENT GUI SCENE")
            if not self.add_shelf_to_existing_stage():
                return False
        else:
            print("OPENING NEW STAGE (original behavior)")
            if not self.load_empty_shop_sync():
                return False

        if not self.create_product_hierarchy():
            return False

        if not self.place_all_products():
            return False

        print("Dynamic shop setup completed successfully!")
        return True


# ------------------------------------------------------------------
# MAIN ENTRY
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("\n==============================")
    print(f"use_current_scene = {use_current_scene}")
    print(f"APPLY_SHELF_WORLD_XFORM = {APPLY_SHELF_WORLD_XFORM}")
    print(f"SHELF_WORLD_XFORM_MODE = {SHELF_WORLD_XFORM_MODE}")
    print(f"SHELF_WORLD_TRANSLATE = {SHELF_WORLD_TRANSLATE}")
    print(f"SHELF_WORLD_ROTATE_ZYX_DEG = {SHELF_WORLD_ROTATE_ZYX_DEG}")
    print("==============================\n")

    placer = DynamicShopPlacer()

    try:
        result = placer.setup_scene_sync()
        if result:
            print("✅ SUCCESS: Products placed!")
        else:
            print("❌ FAILED: See errors above.")
    except Exception as e:
        print(f"❌ ERROR: {e}")

    print("\nScript execution finished.")
