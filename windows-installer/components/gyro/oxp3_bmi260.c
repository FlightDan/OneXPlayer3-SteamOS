// SPDX-License-Identifier: (GPL-2.0-only OR BSD-2-Clause)

#include <linux/i2c.h>
#include <linux/iio/iio.h>
#include <linux/module.h>
#include <linux/pm.h>
#include <linux/regmap.h>

#include "bmi270.h"

static const struct regmap_config bmi270_i2c_regmap_config = {
	.reg_bits = 8,
	.val_bits = 8,
};

static int bmi270_i2c_probe(struct i2c_client *client)
{
	struct regmap *regmap;
	struct device *dev = &client->dev;
	const struct bmi270_chip_info *chip_info;
	unsigned int chip_id;
	int ret;

	/* Match the sensor interface, independently of product and BIOS strings. */
	if (client->addr != 0x68)
		return -ENODEV;

	chip_info = i2c_get_match_data(client);
	if (!chip_info)
		return -ENODEV;

	regmap = devm_regmap_init_i2c(client, &bmi270_i2c_regmap_config);
	if (IS_ERR(regmap))
		return dev_err_probe(dev, PTR_ERR(regmap),
				     "Failed to init i2c regmap");

	/* The shared ACPI ID is also used for other IMUs. Read the real chip ID
	 * before the core can upload firmware or change sensor configuration.
	 */
	ret = regmap_read(regmap, 0x00, &chip_id);
	if (ret)
		return dev_err_probe(dev, ret, "Failed to read BMI260 chip id");
	if (chip_id != 0x27)
		return dev_err_probe(dev, -ENODEV, "BMI260 chip id required");

	return bmi270_core_probe(dev, regmap, chip_info);
}

static const struct acpi_device_id bmi270_acpi_match[] = {
	{ "10EC5280", (kernel_ulong_t)&bmi260_chip_info },
	{ }
};
MODULE_DEVICE_TABLE(acpi, bmi270_acpi_match);

static struct i2c_driver bmi270_i2c_driver = {
	.driver = {
		.name = "oxp3_bmi260",
		.pm = pm_ptr(&bmi270_core_pm_ops),
		.acpi_match_table = bmi270_acpi_match,
	},
	.probe = bmi270_i2c_probe,
};
module_i2c_driver(bmi270_i2c_driver);

MODULE_AUTHOR("Alex Lanzano");
MODULE_DESCRIPTION("BMI260 ACPI binding with chip identity validation");
MODULE_INFO(oxp3_model_policy, "hardware-interface-v2");
MODULE_LICENSE("GPL");
MODULE_IMPORT_NS("IIO_BMI270");
